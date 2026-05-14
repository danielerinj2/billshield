"""
Groq Vision LLM Parser - Final fallback for difficult scanned bills.
Uses Groq's vision models as last resort when other parsers fail.
"""

import os
import json
import base64
import importlib
from pathlib import Path


def _extract_and_repair_json(text: str) -> dict:
    """
    Extract JSON from LLM response that may contain markdown or prose.
    Handles common malformations from vision models like Llama-4-Scout.
    """
    # Remove markdown code fences
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    # Remove leading prose (common pattern: "Based on the image, here is...")
    text = text.strip()

    # Find first { and last }
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:
        raise ValueError("No JSON object found in response")

    json_text = text[start:end + 1]

    # Attempt to parse
    try:
        return json.loads(json_text)
    except json.JSONDecodeError as e:
        # Log the error but raise for tier 3 fallback
        print(f"⚠️  JSON parse error: {e}")
        print(f"📄 Attempted to parse: {json_text[:200]}...")
        raise


def parse_with_groq_vision(image_path: str, doc_type: str = 'bill') -> dict:
    """
    Parse a medical document using Groq's vision model as final fallback.

    Args:
        image_path: Path to the image/PDF file
        doc_type: Type of document ('bill', 'discharge', 'rejection')

    Returns:
        dict: Parsed data in standardized format
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
        prompt = """You are analyzing a medical bill/invoice. Extract ALL line items with MAXIMUM ACCURACY.

CRITICAL: Return ONLY valid JSON. No explanations, no markdown, no "Based on the image" text.

DOCUMENT TYPE DETECTION:
1. HOSPITAL BILL indicators: Room charges, bed charges, operation charges, OT charges, department names
2. PHARMACY BILL indicators: Bill of Supply, MRP, Batch No, Expiry, Tab/Cap/Inj, medicine names
3. LAB BILL indicators: Test names, sample types, diagnostic center, pathology

EXTRACTION RULES FOR HOSPITAL BILLS:

1. PROCEDURE DETECTION (IN ORDER OF PRIORITY):
   a) If procedure name EXPLICITLY written → use exact name
   b) If bill header/diagnosis shows procedure → use that exact text
   c) If ONLY department + generic charge → format as: "[DEPARTMENT] - [CHARGE TYPE]"
      Example: "OBS & GYNECOLOGY - OPERATION CHARGES" (NOT "Caesarean Section" unless visible)

2. ROOM CATEGORY: Extract exact wording
   - ICU / ICCU / NICU / PICU / EMERGENCY
   - DELUXE WARD / PRIVATE ROOM / TWIN SHARING / GENERAL WARD / DAY CARE

EXTRACTION RULES FOR PHARMACY BILLS:

1. Extract product table with: Name, Batch, Expiry, Qty, MRP, Amount
2. Look for: Gross Amount, Discount, Net Amount
3. Preserve exact brand names and dosage forms (Tab/Cap/Inj/Syrup)

EXTRACTION RULES FOR LAB BILLS:

1. Extract each test with name and amount
2. Look for: Test code, sample type, test category

RETURN FORMAT (HOSPITAL BILL):
{
  "hospital_name": "Hospital Name",
  "patient_name": "Patient Name",
  "bill_number": "BILL-123",
  "bill_date": "DD-MMM-YYYY",
  "admission_date": "DD-MMM-YYYY",
  "discharge_date": "DD-MMM-YYYY",
  "department": "Department Name",
  "diagnosis": "diagnosis if visible",
  "procedure_name": "procedure if explicitly visible, else null",
  "procedure_confidence": "high/medium/low",
  "procedure_codes": ["ICD-10 or CPT codes if visible"],
  "room_category": "Room type",
  "total_amount": 63500.00,
  "line_items": [
    {
      "description": "Item description",
      "original_text": "Raw text from bill",
      "quantity": 1.0,
      "rate": 1000.00,
      "amount": 1000.00,
      "category": "Room Charges/Medicine/Procedure Charges/Lab Tests/Consumables/Doctor Fees/Nursing Charges"
    }
  ]
}

RETURN FORMAT (PHARMACY BILL):
{
  "hospital_name": "Pharmacy/Store Name",
  "patient_name": "Patient Name",
  "bill_number": "INV-123",
  "bill_date": "DD-MMM-YYYY",
  "admission_date": null,
  "discharge_date": null,
  "department": null,
  "diagnosis": null,
  "procedure_name": null,
  "procedure_confidence": "low",
  "procedure_codes": [],
  "room_category": null,
  "total_amount": 6454.00,
  "line_items": [
    {
      "description": "Medicine name",
      "original_text": "Raw text",
      "quantity": 10.0,
      "rate": 106.28,
      "amount": 106.28,
      "category": "Medicine",
      "mrp": 106.28,
      "batch_no": "batch if visible",
      "expiry": "expiry if visible"
    }
  ]
}

CRITICAL RULES:
- Return ONLY the JSON object, nothing else
- Parse amounts as numbers (remove ₹, commas)
- DO NOT infer procedure names from department alone
- Extract what is EXPLICITLY VISIBLE only
- If unclear, set fields to null
- For pharmacy bills, preserve MRP, batch, expiry if visible
"""

    elif doc_type == 'discharge':
        prompt = """Extract patient info and diagnosis from this discharge summary.

CRITICAL: Return ONLY valid JSON. No explanations, no markdown.

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
    "procedures": ["procedures performed with exact names"]
  },
  "treatment_summary": "brief summary of treatment given"
}"""

    elif doc_type == 'rejection':
        prompt = """Extract claim rejection details from this insurance document.

CRITICAL: Return ONLY valid JSON. No explanations, no markdown.

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
  "insurer_notes": "any additional notes from insurer"
}"""

    else:
        prompt = "Extract all text from this image and structure it as JSON. Return ONLY JSON, no explanations."

    try:
        # Call Groq vision API
        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
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

        # Extract and repair JSON
        try:
            parsed_data = _extract_and_repair_json(result_text)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"⚠️  TIER 2 JSON extraction failed: {e}")
            print(f"📄 Raw response preview: {result_text[:300]}...")
            raise Exception(f"LLM returned invalid JSON: {e}")

        # Validate required fields
        if doc_type == 'bill':
            if 'line_items' not in parsed_data:
                parsed_data['line_items'] = []
            if 'total_amount' not in parsed_data:
                parsed_data['total_amount'] = sum(
                    item.get('amount', 0) for item in parsed_data.get('line_items', [])
                )

        print(f"✅ TIER 2 SUCCESS: Vision LLM extracted {len(parsed_data.get('line_items', []))} items")
        return parsed_data

    except Exception as e:
        print(f"❌ Groq vision parser failed: {e}")
        raise