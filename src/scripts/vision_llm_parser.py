"""
Vision-LLM fallback for bills that OCR can't parse reliably.

Uses Groq's llama-3.2-90b-vision-preview model to:
1. "See" the bill image directly
2. Extract structured data from the visual layout
3. Return JSON matching the standard parser schema

Activated when:
- OCR confidence < 70%, OR
- Text-based parsing returns <50% of expected fields, OR
- User explicitly requests vision-LLM mode
"""

import base64
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from groq import Groq
from PIL import Image

load_dotenv()


# Groq vision model
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
TEXT_MODEL = "llama-3.3-70b-versatile"

# Max image dimension (Groq has limits)
MAX_IMAGE_SIZE = 2048


def resize_image_if_needed(image: Image.Image, max_size: int = MAX_IMAGE_SIZE) -> Image.Image:
    """Resize image if either dimension exceeds max_size, preserving aspect ratio."""
    if image.width <= max_size and image.height <= max_size:
        return image
    
    ratio = min(max_size / image.width, max_size / image.height)
    new_size = (int(image.width * ratio), int(image.height * ratio))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def image_to_base64(image: Image.Image) -> str:
    """Convert PIL Image to base64 string."""
    import io
    
    # Convert to RGB if needed
    if image.mode != "RGB":
        image = image.convert("RGB")
    
    # Resize if too large
    image = resize_image_if_needed(image)
    
    # Encode as JPEG
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def build_vision_prompt(doc_type: str) -> str:
    """Build the extraction prompt based on document type."""
    
    if doc_type == "bill":
        return """You are analyzing a hospital bill. Extract ALL line items with MAXIMUM ACCURACY.

CRITICAL EXTRACTION RULES:

1. PROCEDURE DETECTION (IN ORDER OF PRIORITY):
   a) If procedure name is EXPLICITLY written anywhere on bill → use exact name
   b) If bill header/diagnosis/admission reason shows procedure → use that exact text
   c) If ONLY department + generic charge visible → DO NOT GUESS, format as:
      "[DEPARTMENT] - [CHARGE TYPE]"
      Example: "CARDIOLOGY - PROCEDURE CHARGES" (NOT "Angioplasty")
      Example: "ORTHOPEDICS - SURGERY CHARGES" (NOT "Knee Replacement")

2. ROOM CATEGORY: Extract exact wording from bill
   - ICU / ICCU / NICU / PICU / EMERGENCY
   - DELUXE WARD / PRIVATE ROOM / TWIN SHARING / GENERAL WARD / DAY CARE

3. COMBINE VISIBLE INFORMATION ONLY:
   ✅ GOOD: "CAESAREAN SECTION - OPERATION CHARGES" (if "Caesarean Section" visible)
   ✅ GOOD: "OBS & GYNECOLOGY - OPERATION CHARGES" (if only department visible)
   ❌ BAD: "ANGIOPLASTY - PROCEDURE CHARGES" (if bill doesn't say "Angioplasty")

4. LOOK FOR THESE PROCEDURE INDICATORS:
   - Explicit procedure names in header/diagnosis section
   - ICD-10 codes if visible
   - CPT codes if visible
   - Admission reason field
   - Doctor's specialization notes

5. FOR MEDICINES:
   - Extract exact brand name from bill
   - Add generic name ONLY if shown in parentheses on bill

RETURN ONLY VALID JSON (no markdown, no explanation):
{
  "hospital_name": "Jubesta Hospital",
  "patient_name": "K. Ruby Joseph",
  "bill_number": "JH-901",
  "bill_date": "02-Feb-2026",
  "admission_date": "29-Jan-2026",
  "discharge_date": "01-Feb-2026",
  "department": "OBS & GYNECOLOGY",
  "procedure_name": "CAESAREAN SECTION",
  "room_category": "DELUXE WARD",
  "total_amount": 63500.00,
  "line_items": [
    {
      "description": "DELUXE WARD BED CHARGES",
      "quantity": 3.0,
      "rate": 2000.00,
      "amount": 6000.00,
      "category": "Room Charges",
      "department_context": "OBS & GYNECOLOGY"
    },
    {
      "description": "CAESAREAN SECTION - OPERATION CHARGES",
      "quantity": 1.0,
      "rate": 22000.00,
      "amount": 22000.00,
      "category": "Procedure Charges",
      "department_context": "OBS & GYNECOLOGY"
    },
    {
      "description": "ANESTHETIC CHARGE",
      "quantity": 1.0,
      "rate": 8000.00,
      "amount": 8000.00,
      "category": "Procedure Charges",
      "department_context": "OBS & GYNECOLOGY"
    }
  ]
}

FIELD DEFINITIONS:
- "procedure_name": Only if explicitly visible on bill, otherwise set to null
- "department_context": Add to each line item for better matching
- "description": Exact text from bill + department context if helpful
- "category": "Room Charges" / "Medicine" / "Procedure Charges" / "Lab Tests" / "Consumables" / "Doctor Fees" / "Nursing Charges"

CRITICAL RULES:
- Parse amounts as numbers (remove ₹, commas)
- DO NOT infer procedure names from department alone
- DO NOT use medical knowledge to guess procedures
- Only extract what is EXPLICITLY VISIBLE on the document
- If procedure unclear, set procedure_name to null and rely on department_context
"""
    
    elif doc_type == "discharge":
        return """You are a medical records expert. Extract structured data from this hospital discharge summary image.

Return ONLY valid JSON (no markdown, no explanation) with this exact structure:

{
  "patient": {
    "name": "string or null",
    "mrn": "string or null",
    "age": number,
    "sex": "Male/Female or null",
    "admission_date": "DD/MM/YYYY or null",
    "discharge_date": "DD/MM/YYYY or null",
    "consultant": "string or null"
  },
  "diagnoses": {
    "primary": "string or null",
    "primary_icd10": "string or null",
    "secondary": ["string"]
  },
  "procedures": [
    {
      "name": "string",
      "date": "DD/MM/YYYY or null",
      "performed_by": "string or null"
    }
  ],
  "medications": [
    {
      "drug": "string",
      "frequency": "string or null",
      "duration": "string or null"
    }
  ]
}

If a field is not visible, use null. Extract all procedures and medications listed."""
    
    elif doc_type == "rejection":
        return """You are an insurance claims expert. Extract structured data from this rejection/settlement letter image.

Return ONLY valid JSON (no markdown, no explanation) with this exact structure:

{
  "insurer": {
    "name": "string or null",
    "irdai_registration": "string or null"
  },
  "claim_metadata": {
    "claim_number": "string or null",
    "policy_number": "string or null",
    "patient_name": "string or null",
    "hospital": "string or null",
    "admission_date": "DD/MM/YYYY or null",
    "discharge_date": "DD/MM/YYYY or null"
  },
  "financial_summary": {
    "amount_claimed": number,
    "amount_settled": number,
    "amount_rejected": number
  },
  "itemized_assessment": [
    {
      "description": "string",
      "amount_claimed": number,
      "amount_settled": number,
      "status": "APPROVED/REJECTED/PARTIALLY APPROVED",
      "cited_clause": "string or null",
      "rejection_reason": "string or null"
    }
  ]
}

Extract ALL items from the itemized assessment table. If a field is not visible, use null."""
    
    else:
        raise ValueError(f"Unknown document type: {doc_type}")


def parse_with_vision_llm(
    image: Image.Image,
    doc_type: str,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Parse a document image using Groq vision model.
    
    Args:
        image: PIL Image of the document
        doc_type: "bill", "discharge", or "rejection"
        api_key: Groq API key (reads from env if not provided)
    
    Returns:
        Structured JSON dict matching parser schema
    """
    if api_key is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in environment")
    
    client = Groq(api_key=api_key)
    
    # Convert image to base64
    image_b64 = image_to_base64(image)
    
    # Build prompt
    prompt = build_vision_prompt(doc_type)
    
    # Call Groq vision API
    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}",
                        },
                    },
                ],
            }
        ],
        temperature=0.0,  # Deterministic extraction
        max_tokens=4096,
    )
    
    # Extract JSON from response
    response_text = response.choices[0].message.content
    
    # Clean markdown fences if present
    response_text = response_text.strip()
    if response_text.startswith("```json"):
        response_text = response_text[7:]
    if response_text.startswith("```"):
        response_text = response_text[3:]
    if response_text.endswith("```"):
        response_text = response_text[:-3]
    response_text = response_text.strip()
    
    # Parse JSON
    try:
        result = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}\n\nResponse:\n{response_text}")
    
    return result


def parse_pdf_with_vision(
    pdf_path: str | Path,
    doc_type: str,
    page_num: int = 0,
) -> dict[str, Any]:
    """Parse a PDF or image using vision-LLM.
    
    Args:
        pdf_path: Path to PDF or image file
        doc_type: "bill", "discharge", or "rejection"
        page_num: Which page to extract (default: first page, ignored for images)
    
    Returns:
        Structured JSON dict
    """
    from pdf2image import convert_from_path
    from PIL import Image
    
    pdf_path = Path(pdf_path)
    
    # Check if it's an image file
    if pdf_path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.webp']:
        # Read image directly
        image = Image.open(pdf_path)
        return parse_with_vision_llm(image, doc_type)
    
    # It's a PDF - convert to image
    images = convert_from_path(str(pdf_path), dpi=300, first_page=page_num+1, last_page=page_num+1)
    
    if not images:
        raise ValueError(f"Could not extract page {page_num} from PDF")
    
    return parse_with_vision_llm(images[0], doc_type)