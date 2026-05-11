"""
Parse the CGHS Rates 2025 PDF into a structured JSON lookup table.

Run from project root:
    python -m src.scripts.parse_cghs_pdf

Output: data/reference/cghs_rates.json
"""

import json
import re
from pathlib import Path

import pdfplumber

INPUT_PDF = Path("data/raw/cghs_rates_2025.pdf")
OUTPUT_JSON = Path("data/reference/cghs_rates.json")

# CGHS codes look like 2 letters + 3 digits, e.g., CN001, LB022, CP004
CGHS_CODE_PATTERN = re.compile(r"^[A-Z]{2}\d{3}$")

# Detect which city tier each page belongs to
TIER_X_PATTERN = re.compile(r"Tier\s*I\s*\(?\s*X\s*City", re.IGNORECASE)
TIER_Y_PATTERN = re.compile(r"Tier\s*II\s*\(?\s*Y\s*City", re.IGNORECASE)
TIER_Z_PATTERN = re.compile(r"Tier\s*III\s*\(?\s*Z\s*City", re.IGNORECASE)


def clean_number(value):
    """Extract digits from a string like '1,275' → 1275. Returns 0 on failure."""
    if value is None:
        return 0
    s = str(value).strip()
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else 0


def detect_tier(page_text, last_tier):
    """Determine which city tier a page belongs to. Falls back to last seen tier."""
    if not page_text:
        return last_tier
    if TIER_X_PATTERN.search(page_text):
        return "X"
    if TIER_Y_PATTERN.search(page_text):
        return "Y"
    if TIER_Z_PATTERN.search(page_text):
        return "Z"
    return last_tier


def parse_cghs_pdf():
    if not INPUT_PDF.exists():
        raise FileNotFoundError(
            f"Could not find {INPUT_PDF}. "
            "Make sure you moved the PDF into data/raw/ and named it cghs_rates_2025.pdf"
        )

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    skipped = 0
    current_tier = "X"  # default until we see a header
    tier_counts = {"X": 0, "Y": 0, "Z": 0}

    print(f"Opening {INPUT_PDF} ...")
    with pdfplumber.open(INPUT_PDF) as pdf:
        print(f"Total pages: {len(pdf.pages)}")

        for page_num, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            current_tier = detect_tier(page_text, current_tier)

            tables = page.extract_tables()
            if not tables:
                continue

            for table in tables:
                for row in table:
                    if not row or len(row) < 6:
                        skipped += 1
                        continue

                    padded = (row + [None] * 7)[:7]
                    sr_no, code, name, non_nabh, nabh, super_spec, speciality = padded

                    code_clean = str(code).strip() if code else ""
                    if not CGHS_CODE_PATTERN.match(code_clean):
                        skipped += 1
                        continue

                    entries.append({
                        "cghs_code": code_clean,
                        "procedure": (name or "").strip(),
                        "rate_non_nabh": clean_number(non_nabh),
                        "rate_nabh": clean_number(nabh),
                        "rate_super_speciality": clean_number(super_spec),
                        "speciality": (speciality or "").strip(),
                        "city_tier": current_tier,
                        "ward_basis": "semi_private",
                    })
                    tier_counts[current_tier] += 1

            if page_num % 50 == 0:
                print(f"  ...page {page_num}, current tier: {current_tier}, total entries: {len(entries)}")

    print(f"\nExtracted {len(entries)} CGHS entries.")
    print(f"  Tier I (X):   {tier_counts['X']}")
    print(f"  Tier II (Y):  {tier_counts['Y']}")
    print(f"  Tier III (Z): {tier_counts['Z']}")
    print(f"Skipped {skipped} rows (headers, blanks, malformed).")

    with open(OUTPUT_JSON, "w") as f:
        json.dump(entries, f, indent=2)

    print(f"Wrote {OUTPUT_JSON}")

    # Sanity check: same procedure across tiers
    print("\nSanity check — Tracheostomy (EP092) across tiers:")
    ep092 = [e for e in entries if e['cghs_code'] == 'EP092']
    for e in ep092:
        print(f"  Tier {e['city_tier']}: Non-NABH ₹{e['rate_non_nabh']}, NABH ₹{e['rate_nabh']}")


if __name__ == "__main__":
    parse_cghs_pdf()