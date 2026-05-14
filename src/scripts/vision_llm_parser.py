"""
Vision-LLM fallback for bills that OCR can't parse reliably.

Uses Groq's llama-4-scout-17b-16e-instruct model to:
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
        return """You are analyzing a hospital bill. Extract data with MAXIMUM ACCURACY.

EXTRACTION HIERARCHY (in priority order):

1. PROCEDURE NAME - Look in this order:
   a) DIAGNOSIS field on bill (highest priority)
   b) ADMISSION REASON / CHIEF COMPLAINT
   c) PROCEDURE field or OPERATION NAME field
   d) ICD-10 / CPT codes (extract the code itself)
   e) Doctor's specialization + visible context
   f) Department name (lowest priority - DO NOT GUESS)

2. LINE ITEM DESCRIPTION RULES:

   RULE A: If procedure name is EXPLICITLY visible on bill:
   - Combine it with each charge
   - Format: "{PROCEDURE_NAME} - {ORIGINAL_CHARGE_TEXT}"
   - Example: Bill says "Diagnosis: Acute Appendicitis" + "Operation Charges ₹45,000"
   - Extract: "ACUTE APPENDICITIS - OPERATION CHARGES"

   RULE B: If procedure name is NOT visible but department is:
   - Use department + original charge
   - Format: "{DEPARTMENT} - {ORIGINAL_CHARGE_TEXT}"
   - Example: Only "Cardiology" + "Procedure Charges"
   - Extract: "CARDIOLOGY - PROCEDURE CHARGES"
   - Set procedure_name to null

   RULE C: For generic charges (Room/Nursing/Medicine):
   - Use original description as-is
   - Don't add procedure context unless useful

3. NEVER INFER OR GUESS:
   ❌ Don't assume "Cardiology" = "Angioplasty"
   ❌ Don't assume "Orthopedics" = "Knee Replacement"
   ❌ Don't use medical knowledge to fill gaps
   ✅ Only extract what is WRITTEN on the bill

4. CONFIDENCE LEVELS:
   - "high": Procedure name explicitly written on bill
   - "medium": Inferred from clear context (diagnosis + department)
   - "low": Only department visible, procedure unclear

RETURN ONLY VALID JSON:
{
  "hospital_name": "exact name from bill",
  "patient_name": "exact name from bill",
  "bill_number": "exact bill/invoice number",
  "bill_date": "DD-MMM-YYYY",
  "admission_date": "DD-MMM-YYYY",
  "discharge_date": "DD-MMM-YYYY",
  "department": "exact department from bill or null",
  "diagnosis": "exact diagnosis text from bill or null",
  "procedure_name": "exact procedure if visible, else null",
  "procedure_confidence": "high|medium|low",
  "procedure_codes": ["ICD-10 or CPT codes if visible"],
  "room_category": "exact room type from bill",
  "total_amount": 0.0,
  "line_items": [
    {
      "description": "formatted per rules above",
      "original_text": "exact text from bill before any modification",
      "quantity": 1.0,
      "rate": 0.0,
      "amount": 0.0,
      "category": "Room Charges|Medicine|Procedure Charges|Lab Tests|Consumables|Doctor Fees|Nursing Charges|Other"
    }
  ]
}

CRITICAL RULES:
- Always include "original_text" with EXACT bill wording (no modification)
- "description" can have procedure/department prefix for better matching
- Parse amounts as numbers (no ₹, no commas)
- If unsure about procedure name, set to null and use department
- Ensure valid JSON (proper commas, no trailing commas)
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