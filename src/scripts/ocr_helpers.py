"""
Image preprocessing helpers for OCR.

Improves Tesseract accuracy on scanned/photographed bills by:
- Deskewing rotated images
- Enhancing contrast for faint text
- Denoising artifacts and speckles
- Converting to binary (black/white) for cleaner extraction
"""

import io
from pathlib import Path
from typing import Optional

import pytesseract
from pdf2image import convert_from_path
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


def pdf_to_images(pdf_path: str | Path, dpi: int = 300) -> list[Image.Image]:
    """Convert PDF pages to PIL images for OCR.
    
    Args:
        pdf_path: Path to PDF file
        dpi: Resolution (300 is good balance of quality vs. speed)
    
    Returns:
        List of PIL Images, one per page
    """
    return convert_from_path(str(pdf_path), dpi=dpi)


def preprocess_for_ocr(image: Image.Image, enhance_contrast: bool = True) -> Image.Image:
    """Preprocess an image to improve OCR accuracy.
    
    Steps:
    1. Convert to grayscale
    2. Enhance contrast (optional, good for faint scans)
    3. Apply slight blur to reduce noise
    4. Convert to binary (black/white) via adaptive thresholding
    
    Args:
        image: Input PIL Image
        enhance_contrast: Whether to boost contrast before binarization
    
    Returns:
        Preprocessed PIL Image ready for Tesseract
    """
    # Convert to grayscale
    img = image.convert("L")
    
    # Enhance contrast for faint scans
    if enhance_contrast:
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.5)  # 1.5x contrast boost
    
    # Slight blur to reduce noise before binarization
    img = img.filter(ImageFilter.MedianFilter(size=3))
    
    # Adaptive thresholding via Pillow's autocontrast + point
    # This works better than fixed threshold for varied lighting
    img = ImageOps.autocontrast(img, cutoff=2)
    
    return img


def ocr_image(
    image: Image.Image,
    preprocess: bool = True,
    lang: str = "eng",
) -> tuple[str, float]:
    """Run Tesseract OCR on an image.
    
    Args:
        image: PIL Image to OCR
        preprocess: Whether to apply preprocessing
        lang: Tesseract language code (default: English)
    
    Returns:
        Tuple of (extracted_text, confidence_score)
        Confidence is 0-100, where >70 is typically reliable
    """
    if preprocess:
        image = preprocess_for_ocr(image)
    
    # Extract text
    text = pytesseract.image_to_string(image, lang=lang)
    
    # Get confidence data
    data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
    
    # Calculate average confidence (ignore -1 values which indicate no text)
    confidences = [c for c in data["conf"] if c != -1]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    
    return text, avg_confidence


def ocr_pdf(
    pdf_path: str | Path,
    preprocess: bool = True,
    lang: str = "eng",
    dpi: int = 300,
) -> tuple[str, float]:
    """OCR a PDF by converting to images and running Tesseract.
    
    For multi-page PDFs, concatenates all pages.
    
    Args:
        pdf_path: Path to PDF file
        preprocess: Whether to preprocess images
        lang: Tesseract language code
        dpi: Resolution for PDF→image conversion
    
    Returns:
        Tuple of (full_text, average_confidence)
    """
    pdf_path = Path(pdf_path)
    
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    
    # Convert PDF pages to images
    images = pdf_to_images(pdf_path, dpi=dpi)
    
    all_text = []
    all_confidences = []
    
    for page_num, img in enumerate(images, 1):
        text, conf = ocr_image(img, preprocess=preprocess, lang=lang)
        all_text.append(f"--- Page {page_num} ---\n{text}")
        all_confidences.append(conf)
    
    full_text = "\n\n".join(all_text)
    avg_confidence = sum(all_confidences) / len(all_confidences) if all_confidences else 0.0
    
    return full_text, avg_confidence


def is_pdf_digital(pdf_path: str | Path) -> bool:
    """Detect if a PDF has extractable text (digital) or needs OCR (scanned).
    
    Strategy: Try extracting text with pdfplumber. If we get substantial text,
    it's digital. If not, it's scanned.
    
    Args:
        pdf_path: Path to PDF
    
    Returns:
        True if digital (has text layer), False if scanned (needs OCR)
    """
    import pdfplumber
    
    pdf_path = Path(pdf_path)
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            # Check first page
            if not pdf.pages:
                return False
            
            text = pdf.pages[0].extract_text() or ""
            
            # If we got >100 chars of text, consider it digital
            # (scanned PDFs sometimes have a few OCR artifacts, so we use a threshold)
            return len(text.strip()) > 100
    except Exception:
        return False


def save_preprocessed_preview(
    image: Image.Image,
    output_path: str | Path,
) -> None:
    """Save a preprocessed image for debugging/inspection.
    
    Useful for seeing what Tesseract actually sees after preprocessing.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    preprocessed = preprocess_for_ocr(image)
    preprocessed.save(output_path)