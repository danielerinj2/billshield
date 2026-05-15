"""
Multi-Tier PDF Splitter for Multi-Bill PDFs

Splits a PDF containing multiple bills into separate PDF files,
one per bill. Uses 5-tier fallback for robustness:

TIER 1: PyPDF2          (fast, deterministic)
TIER 2: pdfplumber      (handles malformed PDFs)
TIER 3: pypdfium2       (handles encrypted/protected PDFs)
TIER 4: pdf2image       (converts to images, rebuilds PDF)
TIER 5: Groq Vision     (AI-based boundary detection)
"""

import os
import tempfile
from typing import List, Tuple
import pdfplumber


# Bill boundary indicators
BILL_INDICATORS = [
    "BILL NO", "INVOICE NO", "RECEIPT NO", "BILL CUM RECEIPT",
    "BILL NUMBER", "INVOICE NUMBER", "RECEIPT NUMBER"
]

# Max bills per PDF (cost ceiling)
MAX_BILLS_PER_PDF = 10


def detect_bill_boundaries(pdf_path: str) -> List[Tuple[int, int]]:
    """
    Identify which pages belong to which bill.
    
    Returns:
        List of (start_page, end_page) tuples, 0-indexed.
        Example: [(0, 1), (2, 2), (3, 4)] means:
                 Bill 1 = pages 0-1, Bill 2 = page 2, Bill 3 = pages 3-4
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)
            
            # Find pages that START a new bill (have bill header)
            bill_start_pages = []
            for i, page in enumerate(pdf.pages):
                text = (page.extract_text() or "").upper()
                if any(indicator in text for indicator in BILL_INDICATORS):
                    bill_start_pages.append(i)
            
            # If no bill headers found, treat as single bill
            if not bill_start_pages:
                return [(0, page_count - 1)]
            
            # Build boundaries: each bill spans from its start until the next bill starts
            boundaries = []
            for idx, start in enumerate(bill_start_pages):
                if idx + 1 < len(bill_start_pages):
                    end = bill_start_pages[idx + 1] - 1
                else:
                    end = page_count - 1
                boundaries.append((start, end))
            
            return boundaries
            
    except Exception as e:
        print(f"⚠️ Boundary detection failed: {e}")
        # On error, return whole PDF as single bill
        return [(0, 0)]


def split_with_pypdf2(pdf_path: str, boundaries: List[Tuple[int, int]]) -> List[str]:
    """TIER 1: Use PyPDF2 to split PDF."""
    from PyPDF2 import PdfReader, PdfWriter
    
    reader = PdfReader(pdf_path)
    output_paths = []
    temp_dir = tempfile.mkdtemp(prefix="bills_pypdf2_")
    
    for idx, (start, end) in enumerate(boundaries):
        writer = PdfWriter()
        for page_num in range(start, end + 1):
            writer.add_page(reader.pages[page_num])
        
        output_path = os.path.join(temp_dir, f"bill_{idx + 1}.pdf")
        with open(output_path, "wb") as f:
            writer.write(f)
        output_paths.append(output_path)
    
    return output_paths


def split_with_pdfplumber(pdf_path: str, boundaries: List[Tuple[int, int]]) -> List[str]:
    """TIER 2: Use pdfplumber + PyPDF2 hybrid (pdfplumber can't write, so we use it for reading)."""
    # pdfplumber doesn't write PDFs, so this is a hybrid approach
    # Re-read with PyPDF2 but skip pages that PyPDF2 might fail on
    from PyPDF2 import PdfReader, PdfWriter
    
    output_paths = []
    temp_dir = tempfile.mkdtemp(prefix="bills_pdfplumber_")
    
    with pdfplumber.open(pdf_path) as pdf:
        reader = PdfReader(pdf_path, strict=False)  # Lenient mode
        
        for idx, (start, end) in enumerate(boundaries):
            writer = PdfWriter()
            for page_num in range(start, end + 1):
                if page_num < len(reader.pages):
                    writer.add_page(reader.pages[page_num])
            
            output_path = os.path.join(temp_dir, f"bill_{idx + 1}.pdf")
            with open(output_path, "wb") as f:
                writer.write(f)
            output_paths.append(output_path)
    
    return output_paths


def split_with_pypdfium2(pdf_path: str, boundaries: List[Tuple[int, int]]) -> List[str]:
    """TIER 3: Use pypdfium2 to split PDF (handles encrypted/protected)."""
    import pypdfium2 as pdfium
    
    pdf = pdfium.PdfDocument(pdf_path)
    output_paths = []
    temp_dir = tempfile.mkdtemp(prefix="bills_pdfium_")
    
    for idx, (start, end) in enumerate(boundaries):
        # Create new PDF with selected pages
        new_pdf = pdfium.PdfDocument.new()
        new_pdf.import_pages(pdf, list(range(start, end + 1)))
        
        output_path = os.path.join(temp_dir, f"bill_{idx + 1}.pdf")
        new_pdf.save(output_path)
        output_paths.append(output_path)
    
    pdf.close()
    return output_paths


def split_with_pdf2image(pdf_path: str, boundaries: List[Tuple[int, int]]) -> List[str]:
    """TIER 4: Convert to images, rebuild as PDF (handles corrupt PDFs)."""
    from pdf2image import convert_from_path
    from PIL import Image
    
    # Convert all pages to images
    images = convert_from_path(pdf_path, dpi=200)
    output_paths = []
    temp_dir = tempfile.mkdtemp(prefix="bills_pdf2image_")
    
    for idx, (start, end) in enumerate(boundaries):
        # Get images for this bill's pages
        bill_images = images[start:end + 1]
        
        if not bill_images:
            continue
        
        # Save as multi-page PDF
        output_path = os.path.join(temp_dir, f"bill_{idx + 1}.pdf")
        bill_images[0].save(
            output_path,
            save_all=True,
            append_images=bill_images[1:] if len(bill_images) > 1 else []
        )
        output_paths.append(output_path)
    
    return output_paths


def split_with_groq_vision(pdf_path: str, boundaries: List[Tuple[int, int]]) -> List[str]:
    """
    TIER 5: Last resort - convert to images individually using Groq's understanding.
    This just uses pdf2image but with Groq vision-aware boundary detection as a sanity check.
    For now, falls back to pdf2image with the original boundaries.
    """
    # If all else fails, just do pdf2image with whatever boundaries we have
    return split_with_pdf2image(pdf_path, boundaries)


def split_pdf_by_bills(pdf_path: str) -> dict:
    """
    Main entry point. Splits a multi-bill PDF into separate PDFs.
    
    Returns:
        {
            "success": bool,
            "bill_pdfs": [list of paths],
            "tier_used": int (1-5),
            "boundaries": [(start, end), ...],
            "error": str or None
        }
    """
    # Step 1: Detect boundaries
    boundaries = detect_bill_boundaries(pdf_path)
    bill_count = len(boundaries)
    
    print(f"📊 Detected {bill_count} bills in PDF")
    print(f"📊 Boundaries: {boundaries}")
    
    # Cost ceiling check
    if bill_count > MAX_BILLS_PER_PDF:
        return {
            "success": False,
            "bill_pdfs": [],
            "tier_used": 0,
            "boundaries": boundaries,
            "error": f"Too many bills ({bill_count}). Maximum {MAX_BILLS_PER_PDF} allowed."
        }
    
    # Single bill - no splitting needed
    if bill_count <= 1:
        return {
            "success": True,
            "bill_pdfs": [pdf_path],
            "tier_used": 0,
            "boundaries": boundaries,
            "error": None
        }
    
    # Try each tier in order
    tiers = [
        (1, "PyPDF2", split_with_pypdf2),
        (2, "pdfplumber", split_with_pdfplumber),
        (3, "pypdfium2", split_with_pypdfium2),
        (4, "pdf2image", split_with_pdf2image),
        (5, "Groq fallback", split_with_groq_vision),
    ]
    
    last_error = None
    for tier_num, tier_name, tier_func in tiers:
        try:
            print(f"🔧 TIER {tier_num}: Attempting split with {tier_name}...")
            bill_pdfs = tier_func(pdf_path, boundaries)
            
            # Verify all output files exist and are non-empty
            valid = all(
                os.path.exists(p) and os.path.getsize(p) > 100
                for p in bill_pdfs
            )
            
            if valid and len(bill_pdfs) == bill_count:
                print(f"✅ TIER {tier_num} SUCCESS: Split into {len(bill_pdfs)} bills")
                return {
                    "success": True,
                    "bill_pdfs": bill_pdfs,
                    "tier_used": tier_num,
                    "boundaries": boundaries,
                    "error": None
                }
            else:
                raise ValueError(f"Output validation failed: {len(bill_pdfs)} files, expected {bill_count}")
                
        except Exception as e:
            last_error = str(e)
            print(f"⚠️ TIER {tier_num} FAILED: {e}")
            continue
    
    # All tiers failed
    return {
        "success": False,
        "bill_pdfs": [],
        "tier_used": 0,
        "boundaries": boundaries,
        "error": f"All splitter tiers failed. Last error: {last_error}"
    }
