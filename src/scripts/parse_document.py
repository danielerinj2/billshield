"""
Unified document parser — handles digital PDFs, scanned PDFs, and images.

Auto-detects input type and routes to appropriate handler:
- Digital PDF → use pdfplumber-based parsers directly
- Scanned PDF → OCR with Tesseract, then parse extracted text
- Image file → OCR with Tesseract, then parse extracted text
- Low OCR confidence → fallback to vision-LLM (not yet implemented)

Usage:
    python -m src.scripts.parse_document <file_path> <document_type>

Where document_type is: bill | discharge | rejection
"""

import json
import sys
from pathlib import Path
from typing import Literal

from .ocr_helpers import is_pdf_digital, ocr_pdf, ocr_image
from .parse_bill_pdf import parse_bill_pdf
from .parse_discharge_pdf import parse_discharge_pdf
from .parse_rejection_pdf import parse_rejection_pdf


DocumentType = Literal["bill", "discharge", "rejection"]

# OCR confidence threshold — below this, we'd use vision-LLM fallback
OCR_CONFIDENCE_THRESHOLD = 70.0


def detect_file_type(file_path: Path) -> Literal["digital_pdf", "scanned_pdf", "image"]:
    """Detect whether file is a digital PDF, scanned PDF, or image."""
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        if is_pdf_digital(file_path):
            return "digital_pdf"
        else:
            return "scanned_pdf"
    elif suffix in {".jpg", ".jpeg", ".png", ".tiff", ".bmp"}:
        return "image"
    else:
        raise ValueError(f"Unsupported file type: {suffix}")


def parse_document(
    file_path: str | Path,
    doc_type: DocumentType,
) -> dict:
    """Parse a document (bill, discharge summary, or rejection letter).

    Automatically handles digital PDFs, scanned PDFs, and images via OCR.

    Args:
        file_path: Path to document (PDF or image)
        doc_type: Type of document to parse

    Returns:
        Structured JSON dict with parsed fields
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Detect file type
    file_type = detect_file_type(file_path)
    print(f"Detected file type: {file_type}")

    # Route to appropriate handler
    if file_type == "digital_pdf":
        # Use existing pdfplumber-based parsers directly
        print("Using direct PDF extraction (pdfplumber)...")
        return _parse_digital_pdf(file_path, doc_type)

    elif file_type == "scanned_pdf":
        # OCR with Tesseract
        print("Running OCR (Tesseract)...")
        text, confidence = ocr_pdf(file_path)
        print(f"OCR confidence: {confidence:.1f}%")
        
        if confidence < OCR_CONFIDENCE_THRESHOLD:
            print(f"⚠️  Low OCR confidence ({confidence:.1f}% < {OCR_CONFIDENCE_THRESHOLD}%)")
            print("Falling back to Vision-LLM...")
            return _parse_with_vision_llm(file_path, doc_type)
        
        # Try text-based parsing
        try:
            result = _parse_ocr_text(text, doc_type, file_path)
            
            # Check if parsing succeeded (heuristic: got >50% of expected header fields)
            if doc_type == "bill":
                header_fields = len([v for v in result.get("header", {}).values() if v])
                if header_fields < 7:  # Less than 50% of 14 expected fields
                    print(f"⚠️  Text-based parsing extracted only {header_fields}/14 header fields")
                    print("Falling back to Vision-LLM...")
                    return _parse_with_vision_llm(file_path, doc_type)
            
            return result
        except Exception as e:
            print(f"⚠️  Text-based parsing failed: {e}")
            print("Falling back to Vision-LLM...")
            return _parse_with_vision_llm(file_path, doc_type)

    elif file_type == "image":
        # OCR image file
        print("Running OCR on image (Tesseract)...")
        from PIL import Image
        img = Image.open(file_path)
        text, confidence = ocr_image(img, preprocess=True)
        print(f"OCR confidence: {confidence:.1f}%")
        
        if confidence < OCR_CONFIDENCE_THRESHOLD:
            print(f"⚠️  Low OCR confidence ({confidence:.1f}% < {OCR_CONFIDENCE_THRESHOLD}%)")
            print("Falling back to Vision-LLM...")
            return _parse_with_vision_llm_image(img, doc_type, file_path)
        
        # Try text-based parsing
        try:
            result = _parse_ocr_text(text, doc_type, file_path)
            
            # Check if parsing succeeded
            if doc_type == "bill":
                header_fields = len([v for v in result.get("header", {}).values() if v])
                if header_fields < 7:
                    print(f"⚠️  Text-based parsing extracted only {header_fields}/14 header fields")
                    print("Falling back to Vision-LLM...")
                    return _parse_with_vision_llm_image(img, doc_type, file_path)
            
            return result
        except Exception as e:
            print(f"⚠️  Text-based parsing failed: {e}")
            print("Falling back to Vision-LLM...")
            return _parse_with_vision_llm_image(img, doc_type, file_path)

    else:
        raise ValueError(f"Unknown file type: {file_type}")


def _parse_digital_pdf(file_path: Path, doc_type: DocumentType) -> dict:
    """Parse a digital PDF using existing pdfplumber-based parsers."""
    if doc_type == "bill":
        return parse_bill_pdf(file_path)
    elif doc_type == "discharge":
        return parse_discharge_pdf(file_path)
    elif doc_type == "rejection":
        return parse_rejection_pdf(file_path)
    else:
        raise ValueError(f"Unknown document type: {doc_type}")


def _parse_ocr_text(text: str, doc_type: DocumentType, source_file: Path) -> dict:
    """Parse OCR'd text using text-based extraction."""
    if doc_type == "bill":
        from .parse_bill_pdf import parse_bill_text
        return parse_bill_text(text, tables=None, source_filename=source_file.name)
    elif doc_type == "discharge":
        from .parse_discharge_pdf import parse_discharge_text
        return parse_discharge_text(text, source_filename=source_file.name)
    elif doc_type == "rejection":
        from .parse_rejection_pdf import parse_rejection_text
        return parse_rejection_text(text, source_filename=source_file.name)
    else:
        raise ValueError(f"Unknown document type: {doc_type}")

def _parse_with_vision_llm(file_path: Path, doc_type: DocumentType) -> dict:
    """Parse a PDF using vision-LLM."""
    from .vision_llm_parser import parse_pdf_with_vision
    from datetime import datetime
    
    result = parse_pdf_with_vision(file_path, doc_type)
    
    # Add metadata
    result["metadata"] = {
        "source_file": file_path.name,
        "parsed_at": datetime.now().isoformat(),
        "parser_version": "1.0",
        "parsing_method": "vision-llm",
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
    }
    
    return result


def _parse_with_vision_llm_image(image, doc_type: DocumentType, source_file: Path) -> dict:
    """Parse an image using vision-LLM."""
    from .vision_llm_parser import parse_with_vision_llm
    from datetime import datetime
    
    result = parse_with_vision_llm(image, doc_type)
    
    # Add metadata
    result["metadata"] = {
        "source_file": source_file.name,
        "parsed_at": datetime.now().isoformat(),
        "parser_version": "1.0",
        "parsing_method": "vision-llm",
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
    }
    
    return result
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m src.scripts.parse_document <file_path> <doc_type>")
        print("  doc_type: bill | discharge | rejection")
        print()
        print("Examples:")
        print("  python -m src.scripts.parse_document data/samples/test_bill_ankit.pdf bill")
        print("  python -m src.scripts.parse_document data/samples/test_bill_ankit_scanned.pdf bill")
        sys.exit(1)

    file_path = Path(sys.argv[1])
    doc_type = sys.argv[2]

    if doc_type not in {"bill", "discharge", "rejection"}:
        print(f"Error: doc_type must be bill|discharge|rejection, got: {doc_type}")
        sys.exit(1)

    print(f"Parsing: {file_path}")
    print(f"Document type: {doc_type}")
    print("-" * 60)

    result = parse_document(file_path, doc_type)

    # Save output
    project_root = Path(__file__).parent.parent.parent
    output_path = project_root / "data" / "uploaded" / f"{file_path.stem}_parsed.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    print(f"\n✅ Parsed successfully")
    print(f"Saved to: {output_path}")

    # Show preview
    if "ocr_text" in result:
        print(f"\nOCR text preview (first 300 chars):")
        print(result["ocr_text"][:300])
    else:
        print(f"\nExtracted fields: {len(result.get('claim_metadata', result.get('patient', {})))} metadata fields")