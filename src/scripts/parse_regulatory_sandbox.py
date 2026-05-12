"""
Parse IRDAI Regulatory Sandbox Regulations 2025 for BillShield roadmap context.

This script does NOT load sandbox rules into ChromaDB.
It creates a lightweight JSON summary for PRD/future-roadmap documentation.
"""

import json
from pathlib import Path

import pdfplumber


RAW_PDF_PATH = Path("data/raw/irdai_regulatory_sandbox_2025.pdf")
OUTPUT_PATH = Path("data/reference/regulatory_sandbox_summary.json")


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract text from all pages of the PDF."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"Could not find PDF: {pdf_path}")

    pages_text = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages_text.append(text)

    return "\n\n".join(pages_text)


def build_summary(text: str) -> dict:
    """Build a roadmap-focused summary for BillShield."""
    return {
        "document": "IRDAI Regulatory Sandbox Regulations 2025",
        "source_file": str(RAW_PDF_PATH),
        "purpose": (
            "Framework for testing innovative insurance products, services, "
            "business models, or processes under regulatory supervision."
        ),
        "utility_for_billshield": "low_for_mvp_high_for_future",
        "should_load_into_agent_chromadb": False,
        "reason_not_loaded_into_agent": (
            "This document is strategic roadmap context. It does not directly "
            "define hospital bill overcharge benchmarks or claim rejection rules "
            "needed for MVP detection."
        ),
        "relevance_to_billshield": (
            "Useful for future integrations with insurers, hospitals, or regulated "
            "claim-dispute workflows."
        ),
        "key_points": [
            "Allows controlled testing of innovative insurance solutions.",
            "May provide temporary regulatory flexibility during testing.",
            "Requires consumer protection safeguards.",
            "Useful for partnerships involving insurers, hospitals, or claim workflows.",
        ],
        "future_use_cases": [
            "Direct hospital integration for real-time bill validation before discharge.",
            "Insurer partnership for automated pre-authorization checks.",
            "Dispute resolution workflow involving insurer or hospital participation.",
            "Pilot program requiring IRDAI-supervised sandbox approval.",
        ],
        "mvp_decision": (
            "Keep as PRD and roadmap context only. Do not use for agent detection logic."
        ),
        "full_text_excerpt": text[:2000],
    }


def main() -> None:
    print(f"Reading: {RAW_PDF_PATH}")

    text = extract_pdf_text(RAW_PDF_PATH)
    summary = build_summary(text)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2, ensure_ascii=False)

    print(f"✅ Saved sandbox regulations summary to {OUTPUT_PATH}")
    print("Decision: Do not load into ChromaDB for MVP agent logic.")


if __name__ == "__main__":
    main()