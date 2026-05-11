"""
Parse insurance rejection / settlement letter PDFs into structured JSON.

Extracts:
- Claim metadata (claim number, policy, dates, pre-auth status)
- Financial summary (claimed vs. settled vs. rejected amounts)
- Itemized assessment with cited policy clauses
- Grievance officer contact details
- Timeline analysis (discharge -> rejection date)

Output: structured rejection data for downstream agent consumption.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pdfplumber


# --- Claim metadata patterns ---
CLAIM_PATTERNS = {
    "claim_number": r"claim\s*number[:\s]+([A-Z0-9/\-]+)",
    "policy_number": r"policy\s*number[:\s]+([A-Z0-9/\-]+)",
    "policy_holder": r"policy\s*holder[:\s]+([A-Z][A-Za-z\s.]+?)(?:\s{2,}|$|insured|sum)",
    "insured_name": r"insured\s*name[:\s]+([A-Z][A-Za-z\s.]+?)(?:\s{2,}|$|sum|hospital)",
    "sum_insured": r"sum\s*insured[:\s]+(?:Rs\.?|₹)?\s*([0-9,]+)",
    "hospital": r"hospital[:\s]+([^\n]+?)(?:\s{2,}|cashless|admission|$)",
    "cashless": r"cashless[:\s]+(yes|no)",
    "admission_date": r"admission\s*date[:\s]*([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4})",
    "discharge_date": r"discharge\s*date[:\s]*([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4})",
    "pre_auth_date": r"pre-?auth\s*date[:\s]*([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4})",
    "pre_auth_status": r"pre-?auth\s*status[:\s]+([^\n]+?)(?:\s{2,}|date|$)",
    "date_of_rejection": r"date\s*of\s*rejection[:\s]*([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4})",
    "date_of_letter": r"date\s*of\s*letter[:\s]*([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4})",
}

# --- Insurer patterns ---
INSURER_PATTERNS = {
    "insurer_name": r"^([A-Z][A-Z\s&.,'-]{10,}(?:INSURANCE|HEALTH|GENERAL).+?)$",
    "irdai_registration": r"IRDAI\s*Registration\s*(?:No\.?|Number)?[:\s]+([0-9]+)",
}

# --- Grievance contact patterns ---
GRIEVANCE_PATTERNS = {
    "officer_name": r"Grievance\s*Officer[:\s]+(?:Mr\.|Ms\.|Mrs\.)?\s*([A-Z][A-Za-z\s.]+?)(?:\s{2,}|email|phone|$)",
    "officer_email": r"email[:\s]+([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})",
    "officer_phone": r"phone[:\s]+(\+?[0-9\-\s]+)(?:\s{2,}|address|$)",
}


def parse_amount(amount_str: Any) -> float:
    """Parse Indian currency amounts to float."""
    if amount_str is None:
        return 0.0

    cleaned = re.sub(r"[₹,/\-\s]|Rs\.?", "", str(amount_str))
    cleaned = cleaned.rstrip(".")

    if not cleaned:
        return 0.0

    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def extract_claim_metadata(text: str) -> dict[str, Any]:
    """Extract claim header fields."""
    metadata = {}

    for field, pattern in CLAIM_PATTERNS.items():
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        metadata[field] = match.group(1).strip() if match else None

    # Convert sum_insured to float
    if metadata.get("sum_insured"):
        metadata["sum_insured"] = parse_amount(metadata["sum_insured"])

    # Convert cashless to bool
    if metadata.get("cashless"):
        metadata["cashless"] = metadata["cashless"].lower() == "yes"

    return metadata


def extract_insurer_info(text: str) -> dict[str, Optional[str]]:
    """Extract insurer name and IRDAI registration."""
    info = {}

    # First all-caps line in the document is typically the insurer name
    for line in text.split("\n")[:5]:
        stripped = line.strip()

        if (
            len(stripped) > 10
            and stripped.isupper()
            and any(x in stripped for x in ["INSURANCE", "HEALTH", "GENERAL"])
        ):
            info["insurer_name"] = stripped
            break
    else:
        info["insurer_name"] = None

    # IRDAI registration
    irdai_match = re.search(
        INSURER_PATTERNS["irdai_registration"],
        text,
        re.IGNORECASE,
    )
    info["irdai_registration"] = (
        irdai_match.group(1).strip() if irdai_match else None
    )

    return info


def extract_financial_summary(text: str) -> dict[str, Any]:
    """Extract claimed/settled/rejected amounts and settlement mode."""
    summary = {
        "amount_claimed": None,
        "amount_settled": None,
        "amount_rejected": None,
        "settlement_mode": None,
    }

    patterns = {
        "amount_claimed": r"total\s*amount\s*claimed[^\n]*?(?:Rs\.?|₹)?\s*([0-9,]+)",
        "amount_settled": r"amount\s*approved\s*(?:&|and)?\s*settled[^\n]*?(?:Rs\.?|₹)?\s*([0-9,]+)",
        "amount_rejected": r"amount\s*rejected[^\n]*?(?:Rs\.?|₹)?\s*([0-9,]+)",
        "settlement_mode": r"settlement\s*mode[:\s]+([^\n]+?)(?:\s{2,}|$)",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)

        if match:
            value = match.group(1).strip()

            if key.startswith("amount_"):
                summary[key] = parse_amount(value)
            else:
                summary[key] = value

    return summary


def extract_itemized_assessment(pdf) -> list[dict[str, Any]]:
    """Extract the line-by-line assessment table.

    Looks for the table with columns:
    Bill Item, Claimed, Settled, Status, Clause, Reason
    """
    items = []

    for page in pdf.pages:
        tables = page.extract_tables()

        for table in tables:
            if not table or len(table) < 2:
                continue

            header_row = [str(c).lower().strip() if c else "" for c in table[0]]

            # Identify the assessment table by its header signature
            has_bill_item = any("bill" in h or "item" in h for h in header_row)
            has_status = any("status" in h for h in header_row)
            has_clause = any("clause" in h for h in header_row)

            if not (has_bill_item and has_status and has_clause):
                continue

            # Map columns
            # Note: pdfplumber sometimes splits column headers across cells.
            # Example: "Bill Item C" and "laimed (Rs)" instead of
            # "Bill Item" and "Claimed (Rs)".
            col_map = {}

            for idx, h in enumerate(header_row):
                if "bill" in h or "item" in h:
                    col_map["description"] = idx
                elif "claimed" in h or "laimed" in h:
                    col_map["amount_claimed"] = idx
                elif "settled" in h:
                    col_map["amount_settled"] = idx
                elif "status" in h:
                    col_map["status"] = idx
                elif "clause" in h:
                    col_map["clause"] = idx
                elif "reason" in h:
                    col_map["reason"] = idx

            if "description" not in col_map:
                continue

            for row in table[1:]:
                if not row or col_map["description"] >= len(row):
                    continue

                if not row[col_map["description"]]:
                    continue

                desc = str(row[col_map["description"]] or "").strip()
                desc = re.sub(r"\s+", " ", desc)

                if not desc:
                    continue

                # Extract amounts - may have text prefix due to cell bleeding.
                claimed_raw = (
                    row[col_map["amount_claimed"]]
                    if "amount_claimed" in col_map
                    and col_map["amount_claimed"] < len(row)
                    else None
                )

                # Strip any leading non-numeric text.
                # Example: "rafting285,000" becomes "285,000".
                if claimed_raw:
                    claimed_raw = re.sub(r"^[^\d,]+", "", str(claimed_raw))

                settled_raw = (
                    row[col_map["amount_settled"]]
                    if "amount_settled" in col_map
                    and col_map["amount_settled"] < len(row)
                    else None
                )

                status_raw = (
                    str(row[col_map["status"]] or "").strip()
                    if "status" in col_map and col_map["status"] < len(row)
                    else None
                )

                # Normalize truncated status.
                # Example: "PARTIALLY APPRO" becomes "PARTIALLY APPROVED".
                if status_raw:
                    status_raw = status_raw.upper()

                    if "PARTIALLY" in status_raw and "APPRO" in status_raw:
                        status_raw = "PARTIALLY APPROVED"
                    elif status_raw == "REJECTED":
                        status_raw = "REJECTED"
                    elif "APPROV" in status_raw:
                        status_raw = "APPROVED"

                clause_raw = (
                    str(row[col_map["clause"]] or "").strip()
                    if "clause" in col_map and col_map["clause"] < len(row)
                    else None
                )

                # Clean clause text.
                # Example: "VECDlause" becomes "Clause".
                if clause_raw:
                    clause_raw = re.sub(r"^[A-Z]{2,4}(?=lause)", "", clause_raw)
                    clause_raw = re.sub(r"^lause", "Clause", clause_raw)

                item = {
                    "description": desc,
                    "amount_claimed": parse_amount(claimed_raw),
                    "amount_settled": parse_amount(settled_raw),
                    "status": status_raw,
                    "cited_clause": clause_raw,
                    "rejection_reason": (
                        str(row[col_map.get("reason", -1)] or "").strip()
                        if "reason" in col_map and col_map["reason"] < len(row)
                        else None
                    ),
                }

                # Compute amount_disputed = claimed - settled
                if (
                    item["amount_claimed"] is not None
                    and item["amount_settled"] is not None
                ):
                    item["amount_disputed"] = (
                        item["amount_claimed"] - item["amount_settled"]
                    )

                items.append(item)

    return items


def extract_grievance_contact(text: str) -> dict[str, Optional[str]]:
    """Extract grievance officer contact details."""
    contact = {}

    for field, pattern in GRIEVANCE_PATTERNS.items():
        match = re.search(pattern, text, re.IGNORECASE)
        contact[field] = match.group(1).strip() if match else None

    return contact


def compute_timeline_metrics(metadata: dict) -> dict[str, Any]:
    """Compute key timelines that the agent will reason about.

    IRDAI rule: insurer must settle claims within 15 days of discharge documents.
    """
    timeline = {
        "discharge_to_rejection_days": None,
        "irdai_15day_rule_violated": None,
    }

    discharge_str = metadata.get("discharge_date")
    rejection_str = metadata.get("date_of_rejection") or metadata.get("date_of_letter")

    if discharge_str and rejection_str:
        try:
            for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
                try:
                    discharge_dt = datetime.strptime(discharge_str, fmt)
                    rejection_dt = datetime.strptime(rejection_str, fmt)
                    delta = (rejection_dt - discharge_dt).days

                    timeline["discharge_to_rejection_days"] = delta
                    timeline["irdai_15day_rule_violated"] = delta > 15
                    break

                except ValueError:
                    continue

        except Exception:
            pass

    return timeline


def _interpret_reconciliation(
    sum_disputed: float,
    reported_rejected: Optional[float],
    item_count: int,
) -> str:
    """Explain what a reconciliation match/mismatch means.

    Helps the agent reason about whether the numbers make sense.
    """
    if reported_rejected is None:
        return "Cannot reconcile: reported rejection amount not found in letter."

    diff = sum_disputed - reported_rejected

    if abs(diff) < 1.0:
        return (
            f"✓ EXACT MATCH: The {item_count} itemized disputes sum to the reported "
            f"rejection amount. All rejected/disputed items are accounted for."
        )

    if diff > 1.0:
        return (
            f"⚠ SUM EXCEEDS REPORTED ({diff:,.0f} more): The itemized table shows "
            f"Rs {diff:,.0f} MORE in disputes than the headline rejection amount. "
            f"This could mean: (a) the table includes items the insurer actually approved "
            f"elsewhere, or (b) the insurer's math is wrong. Cross-check against the full bill."
        )

    abs_diff = abs(diff)
    return (
        f"ℹ SUM LESS THAN REPORTED ({abs_diff:,.0f} missing): The itemized table shows "
        f"Rs {abs_diff:,.0f} LESS in disputes than the headline rejection amount. "
        f"This is COMMON — rejection letters often only list disputed/rejected items in the "
        f"assessment table, while the headline 'Amount Rejected' includes all non-settled "
        f"amounts from the full bill. Cross-check: does the bill have additional items not "
        f"shown in this table that bridge the gap?"
    )


def parse_rejection_pdf(pdf_path: str | Path) -> dict[str, Any]:
    """Main entry point: parse a rejection letter PDF into structured JSON."""
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"Rejection PDF not found: {pdf_path}")

    with pdfplumber.open(pdf_path) as pdf:
        full_text = ""

        for page in pdf.pages:
            full_text += (page.extract_text() or "") + "\n"

        insurer = extract_insurer_info(full_text)
        metadata = extract_claim_metadata(full_text)
        financial = extract_financial_summary(full_text)
        items = extract_itemized_assessment(pdf)
        contact = extract_grievance_contact(full_text)

    timeline = compute_timeline_metrics(metadata)

    # Sanity check: sum of disputed amounts should approximately match amount_rejected.
    sum_disputed = sum(
        item["amount_disputed"]
        for item in items
        if item.get("amount_disputed") is not None
    )

    reported_rejected = financial.get("amount_rejected")

    return {
        "metadata": {
            "source_file": pdf_path.name,
            "parsed_at": datetime.now().isoformat(),
            "parser_version": "1.0",
        },
        "insurer": insurer,
        "claim_metadata": metadata,
        "financial_summary": financial,
        "itemized_assessment": items,
        "grievance_contact": contact,
        "timeline": timeline,
        "reconciliation": {
            "sum_of_disputed_amounts": sum_disputed,
            "reported_amount_rejected": reported_rejected,
            "difference": (
                sum_disputed - reported_rejected
                if reported_rejected
                else None
            ),
            "match": (
                abs(sum_disputed - reported_rejected) < 1.0
                if reported_rejected
                else None
            ),
            "interpretation": _interpret_reconciliation(
                sum_disputed,
                reported_rejected,
                len(items),
            ),
        },
        "summary": {
            "total_items_assessed": len(items),
            "items_partially_approved": sum(
                1
                for i in items
                if i.get("status", "").upper() == "PARTIALLY APPROVED"
            ),
            "items_rejected": sum(
                1
                for i in items
                if i.get("status", "").upper() == "REJECTED"
            ),
            "items_approved": sum(
                1
                for i in items
                if i.get("status", "").upper() == "APPROVED"
            ),
        },
    }


def _save_output(result: dict, source_pdf: Path) -> Path:
    project_root = Path(__file__).parent.parent.parent
    output_path = project_root / "data" / "uploaded" / f"{source_pdf.stem}_parsed.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.scripts.parse_rejection_pdf <path_to_rejection.pdf>")
        print(
            "Example: python -m src.scripts.parse_rejection_pdf "
            "data/samples/test_rejection_ankit.pdf"
        )
        sys.exit(1)

    rejection_path = Path(sys.argv[1])

    print(f"Parsing: {rejection_path}")
    print("-" * 60)

    result = parse_rejection_pdf(rejection_path)

    print("\nINSURER:")
    for k, v in result["insurer"].items():
        status = "✓" if v else "✗"
        print(f"  {status} {k:<25} {v if v else '(not found)'}")

    print("\nCLAIM METADATA:")
    for k, v in result["claim_metadata"].items():
        status = "✓" if v is not None else "✗"
        print(f"  {status} {k:<25} {v if v is not None else '(not found)'}")

    print("\nFINANCIAL SUMMARY:")
    for k, v in result["financial_summary"].items():
        status = "✓" if v is not None else "✗"
        v_display = (
            f"Rs {v:,.2f}"
            if isinstance(v, float)
            else (v if v else "(not found)")
        )
        print(f"  {status} {k:<25} {v_display}")

    print(f"\nITEMIZED ASSESSMENT: {result['summary']['total_items_assessed']} items")
    print(f"  • PARTIALLY APPROVED: {result['summary']['items_partially_approved']}")
    print(f"  • REJECTED:           {result['summary']['items_rejected']}")
    print(f"  • APPROVED:           {result['summary']['items_approved']}")
    print()
    print(
        f"  {'#':<3} {'Description':<40} {'Claimed':>10} "
        f"{'Settled':>10} {'Status':<20} {'Clause':<15}"
    )
    print("  " + "-" * 100)

    for i, item in enumerate(result["itemized_assessment"], 1):
        desc = (item["description"] or "")[:38]
        claimed = (
            f"{item['amount_claimed']:,.0f}"
            if item["amount_claimed"] is not None
            else ""
        )
        settled = (
            f"{item['amount_settled']:,.0f}"
            if item["amount_settled"] is not None
            else ""
        )
        status = (item.get("status") or "")[:18]
        clause = (item.get("cited_clause") or "")[:13]

        print(
            f"  {i:<3} {desc:<40} {claimed:>10} "
            f"{settled:>10} {status:<20} {clause:<15}"
        )

    print("\nGRIEVANCE CONTACT:")
    for k, v in result["grievance_contact"].items():
        status = "✓" if v else "✗"
        print(f"  {status} {k:<25} {v if v else '(not found)'}")

    print("\nTIMELINE ANALYSIS:")
    t = result["timeline"]

    if t["discharge_to_rejection_days"] is not None:
        print(f"  Discharge to rejection: {t['discharge_to_rejection_days']} days")

        if t["irdai_15day_rule_violated"]:
            print("  ⚠️  IRDAI 15-day rule VIOLATED (insurer took > 15 days)")
        else:
            print("  ✓ IRDAI 15-day rule satisfied")
    else:
        print("  Could not compute timeline (dates missing)")

    print("\nRECONCILIATION:")
    r = result["reconciliation"]

    if r["match"] is not None:
        print(f"  Sum of disputed amounts:  Rs {r['sum_of_disputed_amounts']:,.2f}")
        print(f"  Reported amount rejected: Rs {r['reported_amount_rejected']:,.2f}")

        if r.get("difference") is not None:
            diff_sign = "+" if r["difference"] > 0 else ""
            print(f"  Difference:               Rs {diff_sign}{r['difference']:,.2f}")

        print(f"\n  {r['interpretation']}")
    else:
        print(f"  {r['interpretation']}")

    output_path = _save_output(result, rejection_path)

    print(f"\nSaved to: {output_path}")