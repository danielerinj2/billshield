"""
Groq Vision LLM Parser - Final fallback for difficult scanned bills.
Uses Groq's vision models as last resort when other parsers fail.
"""

import os
import json
import base64
import importlib
from pathlib import Path


def parse_with_groq_vision(image_path: str, doc_type: str = 'bill') -> dict:
    """
    Parse a hospital bill using Groq's vision model as final fallback.

    Args:
        image_path: Path to the image/PDF file
        doc_type: Type of document ('bill', 'discharge', 'rejection')

    Returns:
        dict: Parsed bill data in standardized format
    """
    groq_module = importlib.import_module("groq")
    Groq = groq_module.Groq

    api_key = os.getenv('GROQ_API_KEY')
    if not api_key:
        raise RuntimeError("Missing GROQ_API_KEY environment variable")

    client = Groq(api_key=api_key)

    # Read and encode image
    path = Path(image_path)

    # If PDF, convert first page to image
    if path.suffix.lower() == '.pdf':
        pdf2image_module = importlib.import_module("pdf2image")
        convert_from_path = pdf2image_module.convert_from_path

        images = convert_from_path(str(path), first_page=1, last_page=1, dpi=200)
        if not images:
            raise ValueError("Could not convert PDF to image")

        # Save temp image
        temp_img = path.parent / f"{path.stem}_temp.png"
        images[0].save(temp_img, 'PNG')
        image_path = str(temp_img)

    # Encode image to base64
    with open(image_path, 'rb') as f:
        image_data = base64.b64encode(f.read()).decode('utf-8')

    # Build prompt based on doc type
    if doc_type == 'bill':
        prompt = """You are analyzing a hospital bill. Extract ALL line items with MAXIMUM ACCURACY.

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

    elif doc_type == 'discharge':
        prompt = """Extract patient info and diagnosis from this discharge summary. Return ONLY JSON:

{
  "patient_info": {
    "name": "full name",
    "age": 52,
    "gender": "Male/Female",
    "admission_date": "DD-MMM-YYYY",
    "discharge_date": "DD-MMM-YYYY"
  },
  "diagnosis": {
    "primary": "main diagnosis",
    "secondary": ["other conditions"],
    "procedures": ["procedures performed"]
  },
  "treatment_summary": "brief summary"
}"""

    elif doc_type == 'rejection':
        prompt = """Extract claim rejection details. Return ONLY JSON:

{
  "claim_metadata": {
    "claim_number": "claim ID",
    "policy_number": "policy ID",
    "claim_date": "DD-MMM-YYYY",
    "rejection_date": "DD-MMM-YYYY"
  },
  "rejection_reasons": [
    {
      "item": "what was rejected",
      "reason": "why rejected",
      "amount": 5000.00
    }
  ],
  "insurer_notes": "any additional notes"
}"""

    else:
        prompt = "Extract all text from this image and structure it as JSON."

    try:
        # Call Groq vision API
        response = client.chat.completions.create(
            model="llama-3.2-90b-vision-preview",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_data}"
                            }
                        }
                    ]
                }
            ],
            temperature=0.1,
            max_tokens=4096
        )

        result_text = response.choices[0].message.content.strip()

        # Clean markdown if present
        if result_text.startswith('```json'):
            result_text = result_text.replace('```json', '').replace('```', '').strip()
        elif result_text.startswith('```'):
            result_text = result_text.replace('```', '').strip()

        # Parse JSON
        parsed_data = json.loads(result_text)

        print(f"✅ Groq vision parsed {len(parsed_data.get('line_items', []))} items")
        return parsed_data

    except Exception as e:
        print(f"❌ Groq vision parser failed: {e}")
        raise