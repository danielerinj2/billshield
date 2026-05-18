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
import re
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


# ============================================================
# GUARDRAIL 4: PROMPT INJECTION DEFENSE
# ============================================================
def sanitize_prompt(text: str) -> str:
    """Remove prompt injection attempts from text before sending to LLM.
    
    Strips patterns like:
    - "Ignore all previous instructions"
    - "You are now in DAN mode"
    - "Disregard system prompt"
    - Jailbreak attempts
    """
    if not isinstance(text, str):
        return text
    
    # Patterns that indicate prompt injection
    injection_patterns = [
        r'ignore\s+(all\s+)?(previous|prior|above)\s+instructions?',
        r'disregard\s+(the\s+)?(system\s+)?prompt',
        r'you\s+are\s+now\s+(in\s+)?dan\s+mode',
        r'pretend\s+(you\s+are|to\s+be)',
        r'act\s+as\s+if',
        r'bypass\s+(your\s+)?guidelines',
        r'override\s+(your\s+)?instructions',
        r'jailbreak',
        r'developer\s+mode',
        r'god\s+mode',
        r'simulate\s+(being|a)\s+different',
        r'forget\s+(everything|all\s+previous)',
        r'new\s+instructions?:',
    ]
    
    # Remove injection attempts (case-insensitive)
    cleaned = text
    for pattern in injection_patterns:
        cleaned = re.sub(pattern, '[FILTERED]', cleaned, flags=re.IGNORECASE)
    
    # If we filtered anything, log it (but don't break execution)
    if cleaned != text:
        print("⚠️ SECURITY: Prompt injection attempt detected and filtered")
    
    return cleaned


# ============================================================
# GUARDRAIL 5: OUTPUT VALIDATION
# ============================================================
def validate_output(result: dict[str, Any]) -> tuple[bool, str]:
    """Validate LLM output for hallucinations and data quality.
    
    Returns (is_valid, warning_message).
    """
    warnings = []
    
    # Check 1: Verify line items exist
    line_items = result.get('line_items', [])
    if not line_items:
        return False, "No line items extracted"
    
    # Check 2: Verify amounts are reasonable
    for idx, item in enumerate(line_items):
        amount = item.get('amount', 0)
        
        # Flag suspiciously high amounts (>₹1 lakh per item)
        if amount > 100000:
            warnings.append(f"Item {idx+1} has unusually high amount: ₹{amount:,.2f}")
        
        # Flag negative amounts (except for returns)
        if amount < 0 and 'return' not in item.get('description', '').lower():
            warnings.append(f"Item {idx+1} has negative amount without 'return' keyword")
    
    # Check 3: Verify total matches sum of line items (within 5% tolerance)
    total_claimed = result.get('total_amount', 0)
    total_calculated = sum(item.get('amount', 0) for item in line_items)
    
    if total_claimed > 0 and total_calculated > 0:
        diff_percent = abs(total_claimed - total_calculated) / total_claimed * 100
        if diff_percent > 5:
            warnings.append(
                f"Total mismatch: Bill shows ₹{total_claimed:,.2f}, "
                f"line items sum to ₹{total_calculated:,.2f} ({diff_percent:.1f}% difference)"
            )
    
    # Check 4: Verify required fields are present
    required_fields = ['hospital_name', 'bill_number', 'patient_name']
    missing_fields = [f for f in required_fields if not result.get(f)]
    
    if missing_fields:
        warnings.append(f"Missing critical fields: {', '.join(missing_fields)}")
    
    # Check 5: Flag if ALL line items have same amount (likely extraction error)
    amounts = [item.get('amount', 0) for item in line_items]
    if len(set(amounts)) == 1 and len(amounts) > 3:
        warnings.append("All line items have identical amounts - possible extraction error")
    
    # Return validation result
    if warnings:
        warning_msg = " | ".join(warnings)
        print(f"⚠️ OUTPUT VALIDATION WARNINGS: {warning_msg}")
        return True, warning_msg  # Allow with warnings
    
    return True, "OK"


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

CRITICAL: Hospital bills often have TWO parts:
1. SUMMARY PAGE (page 1) - shows category totals like "MEDICINE CHARGES: ₹18,826"
2. DETAILED PAGES (pages 2+) - shows individual items like "Magnex Forte 1.5gm - qty 4 - ₹3,191"

YOU MUST EXTRACT BOTH. Ignore the summary page categories and focus on the detailed line items.

EXTRACTION HIERARCHY (in priority order):

1. PROCEDURE NAME - Look in this order:
   a) DIAGNOSIS field on bill (highest priority)
   b) ADMISSION REASON / CHIEF COMPLAINT
   c) PROCEDURE field or OPERATION NAME field
   d) ICD-10 / CPT codes (extract the code itself)
   e) Doctor's specialization + visible context
   f) Department name (lowest priority - DO NOT GUESS)

2. LINE ITEM EXTRACTION RULES:
   
   CRITICAL: Extract EVERY INDIVIDUAL ITEM from the detailed pages, NOT category summaries.
   
   FOR MEDICINES/DRUGS:
   - Extract: Drug name, strength/dosage, batch number, quantity, rate per unit, total amount
   - Example: "Magnex Forte 1.5gm - Batch: 30049099 - Qty: 4 - Rate: ₹797.93 - Amount: ₹3,191.74"
   - Include consumables: syringes, gauze, cannulas, IV sets, etc.
   
   FOR LAB TESTS:
   - Extract: Test name, individual test price FROM THE DETAILED PAGES
   - CRITICAL: Each lab test has its OWN amount on pages 3-8. DO NOT use the category total from page 1.
   - Example: "Complete Blood Count (CBC)" on page 7 shows ₹280.00 - use 280.00, NOT the LABORATORY total
   - Example: "Blood Urea" on page 7 shows ₹100.00 - use 100.00, NOT the LABORATORY total
   - If you see "LABORATORY: ₹4,460" on page 1, SKIP IT - that's a category summary
   - Only extract individual test lines with their individual amounts
   
   FOR PROCEDURES:
   - Extract: Procedure name, procedure charges
   - Example: "Clinical Support Care - ₹75.00"
   
   FOR ROOM CHARGES:
   - Extract: Room type, number of days, daily rate, total
   - Example: "A/C Room - 2 days - ₹1,850/day - ₹3,700"
   
   FOR CONSULTATIONS:
   - Extract: Doctor name/specialization, consultation type, amount
   - Example: "IP Consultation - Dr. Jaisankar P - ₹1,000"

3. WHAT NOT TO EXTRACT AS LINE ITEMS:
   - Page 1 category summaries like "MEDICINE CHARGES: ₹18,826" - SKIP
   - Page 1 category summaries like "LABORATORY: ₹4,460" - SKIP
   - Any line that's just a category name + total amount - SKIP
   - Only extract INDIVIDUAL items from pages 3-8 with their INDIVIDUAL amounts
   
4. CRITICAL AMOUNT EXTRACTION RULE:
   - Each line item must have its OWN specific amount
   - "Complete Blood Count (CBC) - ₹280" → amount: 280
   - "Blood Urea - ₹100" → amount: 100
   - If you're tempted to use ₹4,460 for a lab test, STOP - that's the category total, not the individual test amount

5. QUANTITY AND RATE:
   - Always extract quantity if visible (even if it's 1)
   - Always extract per-unit rate if visible
   - Calculate: amount should equal rate × quantity (within rounding tolerance)

6. RETURNS/CREDITS:
   - If you see negative amounts or "RETURN DETAILS", mark quantity as negative
   - Example: "Syringe - 5ml (Bd) - RETURN - Qty: -2 - Amount: -₹18.84"

RETURN FORMAT:
{
  "hospital_name": "string",
  "bill_number": "string",
  "bill_date": "YYYY-MM-DD",
  "patient_name": "string",
  "diagnosis": "string or null",
  "procedure_name": "string or null",
  "doctor_name": "string or null",
  "admission_date": "YYYY-MM-DD or null",
  "discharge_date": "YYYY-MM-DD or null",
  "room_type": "string or null",
  "total_amount": number,
  "line_items": [
    {
      "description": "Full item description with details",
      "category": "MEDICINE" | "LAB" | "ROOM" | "CONSULTATION" | "PROCEDURE" | "CONSUMABLE" | "OTHER",
      "quantity": number,
      "rate": number or null,
      "amount": number,
      "batch_no": "string or null (for medicines)",
      "hsn_code": "string or null"
    }
  ]
}

EXAMPLE OUTPUT for a drug line:
{
  "description": "Magnex Forte 1.5gm (Batch: 30049099)",
  "category": "MEDICINE",
  "quantity": 4,
  "rate": 797.93,
  "amount": 3191.74,
  "batch_no": "30049099",
  "hsn_code": null
}

EXAMPLE OUTPUT for a lab test:
{
  "description": "Complete Blood Count (CBC)",
  "category": "LAB",
  "quantity": 1,
  "rate": 280.00,
  "amount": 280.00,
  "batch_no": null,
  "hsn_code": null
}

Extract ONLY valid JSON. No markdown fences, no preamble, no explanation.
"""

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
    
    # ============================================================
    # GUARDRAIL 4: Sanitize prompt before sending to LLM
    # ============================================================
    prompt = sanitize_prompt(prompt)
    
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
    
    # ============================================================
    # GUARDRAIL 5: Validate output before returning
    # ============================================================
    is_valid, validation_msg = validate_output(result)
    if not is_valid:
        raise ValueError(f"Output validation failed: {validation_msg}")
    
    # Add validation warnings to result metadata
    if validation_msg != "OK":
        result['_validation_warnings'] = validation_msg
    
    return result


def parse_pdf_with_vision(
    pdf_path: str | Path,
    doc_type: str,
    page_num: int = 0,  # DEPRECATED - now processes all pages
) -> dict[str, Any]:
    """Parse a PDF or image using vision-LLM.
    
    Args:
        pdf_path: Path to PDF or image file
        doc_type: "bill", "discharge", or "rejection"
        page_num: DEPRECATED - function now processes all pages automatically
    
    Returns:
        Structured JSON dict with aggregated data from all pages
    """
    from pdf2image import convert_from_path
    from PIL import Image
    
    pdf_path = Path(pdf_path)
    
    # Check if it's an image file
    if pdf_path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.webp']:
        # Read image directly
        image = Image.open(pdf_path)
        return parse_with_vision_llm(image, doc_type)
    
    # It's a PDF - convert ALL pages to images
    print(f"Converting PDF to images (all pages)...")
    images = convert_from_path(str(pdf_path), dpi=150)
    
    if not images:
        raise ValueError(f"Could not extract any pages from PDF")
    
    print(f"Processing {len(images)} pages...")
    
    # Process each page
    all_results = []
    for page_idx, image in enumerate(images, start=1):
        print(f"  Processing page {page_idx}/{len(images)}...")
        page_result = parse_with_vision_llm(image, doc_type)
        all_results.append(page_result)
    
    # Aggregate results
    if doc_type == "bill":
        return _aggregate_bill_pages(all_results)
    else:
        # For discharge/rejection, just return the first page for now
        # (multi-page aggregation for these types can be added later)
        return all_results[0]


def _aggregate_bill_pages(page_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate bill data from multiple pages.
    
    Strategy:
    1. Take patient/hospital/bill metadata from page 1
    2. Merge all line_items from all pages
    3. Use the total_amount from page 1 (final page often has summary)
       OR sum all line items if total is missing
    """
    if not page_results:
        raise ValueError("No pages to aggregate")
    
    # Start with page 1 as base
    aggregated = page_results[0].copy()
    
    # Collect all line items from all pages
    all_line_items = []
    for page in page_results:
        if "line_items" in page and page["line_items"]:
            all_line_items.extend(page["line_items"])
    
    aggregated["line_items"] = all_line_items
    
    # If total_amount is missing or 0, sum the line items
    if not aggregated.get("total_amount") or aggregated["total_amount"] == 0:
        aggregated["total_amount"] = sum(
            item.get("amount", 0) for item in all_line_items
        )
    
    print(f"Aggregated {len(all_line_items)} line items from {len(page_results)} pages")
    print(f"Total amount: ₹{aggregated['total_amount']:,.2f}")
    
    return aggregated