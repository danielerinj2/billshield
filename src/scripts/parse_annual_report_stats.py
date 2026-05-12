"""
Extract basic statistics from IRDAI Annual Report 2024 for BillShield PRD context.

This is for problem validation, market sizing, and pitch/PRD support.
Do not use these statistics as agent detection rules.
"""

import json
import re
from pathlib import Path

import pdfplumber


RAW_PDF_PATH = Path("data/raw/irdai_annual_report_2024.pdf")
OUTPUT_PATH = Path("data/reference/irdai_annual_report_stats.json")


def main():
    if not RAW_PDF_PATH.exists():
        raise FileNotFoundError(f"Missing PDF: {RAW_PDF_PATH}")

    print(f"Reading: {RAW_PDF_PATH}")

    text_parts = []

    with pdfplumber.open(RAW_PDF_PATH) as pdf:
        for page in pdf.pages[:50]:
            text_parts.append(page.extract_text() or "")

    text = "\n\n".join(text_parts)

    stats = {
        "document": "IRDAI Annual Report 2024",
        "source_file": str(RAW_PDF_PATH),
        "purpose": "PRD problem statement, market sizing, and pitch context.",
        "should_load_into_agent_chromadb": False,
        "statistics": {},
        "use_in_prd": [
            "Problem validation: claim rejection and grievance context.",
            "Market sizing: health insurance scale and growth.",
            "Competitive context: insurer performance and complaints.",
        ],
        "manual_review_needed": True,
    }

    claim_matches = re.findall(
        r"claims?.{0,120}?₹\s*([0-9,]+)\s*(crore|lakh)",
        text,
        re.IGNORECASE,
    )
    if claim_matches:
        stats["statistics"]["claims_amount"] = (
            f"₹{claim_matches[0][0]} {claim_matches[0][1]}"
        )

    grievance_matches = re.findall(
        r"grievance.{0,120}?([0-9,]+)",
        text,
        re.IGNORECASE,
    )
    if grievance_matches:
        stats["statistics"]["grievances_filed_candidate"] = grievance_matches[0]

    policy_matches = re.findall(
        r"policies.{0,120}?([0-9,]+)\s*(million|lakh|crore)",
        text,
        re.IGNORECASE,
    )
    if policy_matches:
        stats["statistics"]["policies_in_force_candidate"] = (
            f"{policy_matches[0][0]} {policy_matches[0][1]}"
        )

    stats["full_text_sample"] = text[:3000]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(stats, file, indent=2, ensure_ascii=False)

    print(f"✅ Saved to {OUTPUT_PATH}")
    print("Extracted candidate statistics:")
    if stats["statistics"]:
        for key, value in stats["statistics"].items():
            print(f"  {key}: {value}")
    else:
        print("  No clean statistics found automatically. Use full_text_sample for manual review.")


if __name__ == "__main__":
    main()