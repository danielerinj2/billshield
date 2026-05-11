"""
Parse hospital bill PDFs into structured JSON.

Handles digital PDFs with itemized tables (clean text-layer PDFs).
Scanned PDFs and image bills are handled separately (Day 2 afternoon).

Output: structured bill data for downstream agent consumption.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pdfplumber


# --- Header field extraction patterns ---
# OCR-aware patterns: handle variable whitespace between labels and values
HEADER_PATTERNS = {
    "hospital_name": r"^([A-Z][A-Z\s&,.'-]{5,})\s*$",  # All-caps line near top
    "bill_number": r"bill\s*number[:\s]+([A-Z0-9/\-.]+)",
    "bill_date": r"bill\s*date[:\s]+([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4})",
    "patient_name": r"patient\s*name[:\s]+([A-Z][A-Za-z\s.]+?)(?:\s+Age[/\s]|$)",
    "patient_id": r"patient\s*id[:\s]+([A-Z0-9\-/]+)",
    "age_sex": r"age[/\s]*sex[:\s]+([0-9]+\s*(?:Years?|Yrs?)?\s*/\s*(?:Male|Female|M|F))",
    "ward_type": r"ward\s*type[:\s]+([A-Za-z\s()]+?)(?:\s+Discharge|$)",
    "admission_date": r"admission\s*date[:\s]+([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4})",
    "discharge_date": r"discharge\s*date[:\s]+([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4})",
    "diagnosis": r"diagnosis[:\s]+([^\n:]+?)(?:\s+Procedure[:\s]|$)",
    "procedure": r"procedure[:\s]+([^\n:]+?)(?:\s+Consultant[:\s]|$)",
    "consultant": r"consultant[:\s]+([^\n:]+?)(?:\s+Insurance[:\s]|$)",
    "insurance": r"insurance[:\s]+([^\n]+?)(?:\s+CITY|$)",
}


def parse_amount(amount_str: Any) -> float:
    """Parse Indian currency amounts to float.

    Handles: '1,23,456.50', 'Rs. 19000/-', '₹5,400', '5400.00', None, ''.
    """
    if amount_str is None:
        return 0.0
    # Strip currency symbols, commas, dashes, whitespace — but PRESERVE decimal points
    cleaned = re.sub(r"[₹,/\-\s]|Rs\.?", "", str(amount_str))
    # Also strip trailing periods that aren't decimal markers (e.g., "Rs.")
    cleaned = cleaned.rstrip(".")
    if not cleaned:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_quantity(qty_str: Any) -> float:
    """Parse quantity: '12', 'Qty: 2', 'x2', '3 days'."""
    if qty_str is None:
        return 1.0
    numbers = re.findall(r"\d+\.?\d*", str(qty_str))
    if numbers:
        try:
            return float(numbers[0])
        except ValueError:
            return 1.0
    return 1.0


def extract_header_fields(text: str) -> dict[str, Optional[str]]:
    """Extract header fields from the bill's full text.
    
    Handles both clean PDF text and OCR'd text with variable spacing.
    """
    header = {}
    
    # Apply regex patterns
    for field, pattern in HEADER_PATTERNS.items():
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            value = match.group(1).strip()
            # Clean up: remove trailing colons, extra whitespace
            value = re.sub(r"\s+", " ", value).strip(": ")
            header[field] = value if value else None
        else:
            header[field] = None
    
    # Hospital name: take first all-caps line >5 chars
    if not header.get("hospital_name"):
        for line in text.split("\n")[:10]:
            stripped = line.strip()
            if len(stripped) > 5 and stripped.isupper() and "HOSPITAL" in stripped:
                header["hospital_name"] = stripped
                break
    
    # Parse age/sex if captured together
    if header.get("age_sex"):
        age_sex_match = re.search(r"(\d+)\s*(?:Years?|Yrs?)?\s*/\s*(Male|Female|M|F)", header["age_sex"], re.IGNORECASE)
        if age_sex_match:
            header["age"] = age_sex_match.group(1)
            header["sex"] = age_sex_match.group(2)
    
    return header


def identify_columns(header_row: list) -> dict[str, Optional[int]]:
    """Map column position to semantic field by inspecting the header row."""
    cols = {"date": None, "description": None, "qty": None, "rate": None, "amount": None}

    for idx, cell in enumerate(header_row):
        if not cell:
            continue
        cell_lower = str(cell).lower().strip()

        if any(x in cell_lower for x in ["date"]):
            cols["date"] = idx
        elif any(x in cell_lower for x in ["description", "particulars", "item", "service", "details"]):
            cols["description"] = idx
        elif any(x in cell_lower for x in ["qty", "quantity", "nos", "units"]):
            cols["qty"] = idx
        elif any(x in cell_lower for x in ["rate", "price", "unit cost", "per unit"]):
            cols["rate"] = idx
        elif any(x in cell_lower for x in ["amount", "total", "charges", "value"]):
            cols["amount"] = idx

    return cols


def extract_line_items_from_text(text: str) -> list[dict[str, Any]]:
    """Extract line items from OCR'd text when table structure isn't available.

    Looks for patterns like:
    11/03/2025 Room Charges (Private Deluxe) 4 8,500.00 34,000.00
    """
    items = []

    # Pattern: date | description | qty | rate | amount
    # Date is optional (some bills don't include per-item dates)
    pattern = r"(?:(\d{1,2}/\d{1,2}/\d{2,4})\s+)?(.+?)\s+(\d+)\s+([\d,]+(?:\.\d{2})?)\s+([\d,]+(?:\.\d{2})?)\s*$"

    for line in text.split("\n"):
        line = line.strip()
        if not line or len(line) < 20:
            continue

        match = re.search(pattern, line)
        if match:
            date_str, desc, qty_str, rate_str, amount_str = match.groups()

            # Skip footer lines
            if any(kw in desc.lower() for kw in ["subtotal", "gst", "total", "grand"]):
                continue

            items.append({
                "date": date_str,
                "description": desc.strip(),
                "quantity": int(qty_str) if qty_str else None,
                "rate": parse_amount(rate_str),
                "amount": parse_amount(amount_str),
            })

    return items


def extract_line_items_from_tables(tables: list) -> list[dict[str, Any]]:
    """Extract line items from pdfplumber tables."""
    items = []

    for table in tables:
        if not table or len(table) < 2:
            continue

        cols = identify_columns(table[0])

        # Need at minimum description and amount columns
        if cols["description"] is None or cols["amount"] is None:
            continue

        for row in table[1:]:
            if not row:
                continue

            # Skip rows shorter than needed
            max_idx = max(i for i in cols.values() if i is not None)
            if len(row) <= max_idx:
                continue

            desc = str(row[cols["description"]] or "").strip()
            desc = re.sub(r"\s+", " ", desc)
            amount_raw = row[cols["amount"]]
            amount = parse_amount(amount_raw)

            # Skip empty rows
            if not desc:
                continue

            # Skip footer rows (subtotal, GST, grand total)
            # Use word-boundary matching so "vat" doesn't match "private", etc.
            desc_lower = desc.lower()
            footer_keywords = [
                "sub total", "subtotal", "grand total", "gst", "vat",
                "discount", "net payable", "total payable"
            ]
            if any(re.search(rf"\b{re.escape(kw)}\b", desc_lower) for kw in footer_keywords):
                continue

            # Skip header-like rows that snuck into body
            if desc_lower in ["description", "particulars", "item", "service"]:
                continue

            # Skip zero-amount rows (likely artifacts)
            if amount == 0:
                continue

            item = {
                "description": desc,
                "amount": amount,
            }

            if cols["date"] is not None and cols["date"] < len(row):
                item["date"] = str(row[cols["date"]] or "").strip() or None

            if cols["qty"] is not None and cols["qty"] < len(row):
                item["quantity"] = parse_quantity(row[cols["qty"]])

            if cols["rate"] is not None and cols["rate"] < len(row):
                item["rate"] = parse_amount(row[cols["rate"]])

            items.append(item)

    return items


def extract_totals(text: str) -> dict[str, float]:
    """Extract subtotal, GST, and grand total from the bill footer."""
    totals = {"subtotal": 0.0, "gst": 0.0, "grand_total": 0.0}

    patterns = {
        "subtotal": r"sub\s*total[:\s]*(?:Rs\.?|₹)?\s*([\d,]+(?:\.\d{2})?)",
        "gst": r"GST[^:]*[:\s]*(?:Rs\.?|₹)?\s*([\d,]+(?:\.\d{2})?)",
        "grand_total": r"grand\s*total[:\s]*(?:Rs\.?|₹)?\s*([\d,]+(?:\.\d{2})?)",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            totals[key] = parse_amount(match.group(1))

    return totals


def parse_bill_text(
    full_text: str,
    tables: list[list[list[str]]] | None = None,
    source_filename: str = "unknown.pdf",
) -> dict[str, Any]:
    """Parse bill text from PDF extraction or OCR into structured JSON.

    Args:
        full_text: Complete bill text
        tables: Optional list of tables from pdfplumber, or None if from OCR
        source_filename: Name of source file for metadata

    Returns:
        Structured bill data
    """
    header = extract_header_fields(full_text)

    # Line items: try tables first, fall back to text-based extraction
    if tables:
        line_items = extract_line_items_from_tables(tables)
    else:
        line_items = extract_line_items_from_text(full_text)

    totals = extract_totals(full_text)

    # Reconciliation
    computed_total = sum(item["amount"] for item in line_items if item.get("amount"))

    reconciliation_match = None
    if totals.get("grand_total"):
        reconciliation_match = abs(
            totals["grand_total"] - (computed_total + totals["gst"])
        ) < 1.0

    return {
        "metadata": {
            "source_file": source_filename,
            "parsed_at": datetime.now().isoformat(),
            "parser_version": "1.0",
        },
        "header": header,
        "line_items": line_items,
        "totals": {
            "extracted_subtotal": totals["subtotal"],
            "extracted_gst": totals["gst"],
            "extracted_grand_total": totals["grand_total"],
            "computed_from_line_items": computed_total,
            "reconciliation_match": reconciliation_match,
        },
        "summary": {
            "line_item_count": len(line_items),
        },
    }


def parse_bill_pdf(pdf_path: str | Path) -> dict[str, Any]:
    """Parse a hospital bill PDF into structured JSON.

    This is the PDF-specific wrapper. For OCR'd text, use parse_bill_text directly.
    """
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"Bill PDF not found: {pdf_path}")

    with pdfplumber.open(pdf_path) as pdf:
        # Extract text from all pages
        full_text = ""
        for page in pdf.pages:
            full_text += (page.extract_text() or "") + "\n"

        # Extract tables
        all_tables = []
        for page in pdf.pages:
            page_tables = page.extract_tables()
            if page_tables:
                all_tables.extend(page_tables)

    result = parse_bill_text(full_text, all_tables, pdf_path.name)
    result["metadata"]["page_count"] = _get_page_count(pdf_path)

    return result


def _get_page_count(pdf_path: Path) -> int:
    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)


def _save_output(result: dict, source_pdf: Path) -> Path:
    """Save parsed result to data/uploaded/."""
    project_root = Path(__file__).parent.parent.parent
    output_path = project_root / "data" / "uploaded" / f"{source_pdf.stem}_parsed.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.scripts.parse_bill_pdf <path_to_bill.pdf>")
        print("Example: python -m src.scripts.parse_bill_pdf data/samples/test_bill_ankit.pdf")
        sys.exit(1)

    bill_path = Path(sys.argv[1])
    print(f"Parsing: {bill_path}")
    print("-" * 60)

    result = parse_bill_pdf(bill_path)

    # Print summary
    print(f"\nHEADER FIELDS EXTRACTED:")
    for k, v in result["header"].items():
        status = "✓" if v else "✗"
        v_display = v if v else "(not found)"
        print(f"  {status} {k:<20} {v_display}")

    print(f"\nLINE ITEMS: {result['summary']['line_item_count']} extracted")
    print(f"  {'#':<4} {'Description':<50} {'Qty':>6} {'Rate':>10} {'Amount':>12}")
    print("  " + "-" * 84)
    for i, item in enumerate(result["line_items"], 1):
        desc = item["description"][:48]
        qty = item.get("quantity", "")
        rate = item.get("rate", "")
        amount = item["amount"]
        print(f"  {i:<4} {desc:<50} {qty:>6} {rate:>10,.0f} {amount:>12,.0f}")

    print(f"\nTOTALS:")
    t = result["totals"]
    print(f"  Extracted Grand Total:    Rs {t['extracted_grand_total']:>14,.2f}")
    print(f"  Computed from line items: Rs {t['computed_from_line_items']:>14,.2f}")
    print(f"  Extracted GST:            Rs {t['extracted_gst']:>14,.2f}")
    if t["reconciliation_match"] is not None:
        match_status = "✓ MATCH" if t["reconciliation_match"] else "✗ MISMATCH"
        print(f"  Reconciliation:           {match_status}")

    output_path = _save_output(result, bill_path)
    print(f"\nSaved to: {output_path}")