"""
Parse the NPPA Updated Drug Price List into a structured JSON lookup table.

Source: NPPA notification compilation with ceiling prices for scheduled drugs
under DPCO 2013, effective 1 April 2025 onwards (with WPI 1.74028% adjustment).

SCOPE: This parser handles the main scheduled-drug table (pages 1-37 of the
PDF), which contains ~903 single-active-ingredient generic scheduled drugs
(alphabetical: 5-aminosalicylic Acid through Cefuroxime/Clopidogrel range).

The deeper sections of the PDF (pages 38+) contain manufacturer-specific
brand combinations with a fundamentally different table structure (8-12 line
tall entries, varying column boundaries per page). These are out of scope
for v1 and supplemented via a hand-curated common-drugs file.

Run from project root:
    python -m src.scripts.parse_nppa_pdf

Output: data/reference/nppa_drugs.json
"""

import json
import re
from pathlib import Path

import pdfplumber

INPUT_PDF = Path("data/raw/nppa_drugs_2025.pdf")
OUTPUT_JSON = Path("data/reference/nppa_drugs.json")

# Stop after this page — main scheduled-drug table boundary
MAIN_TABLE_LAST_PAGE = 37

# Column X-coordinate boundaries (in PDF points)
COL_SLNO_MAX = 70
COL_DRUG_MAX = 230
COL_DOSAGE_MAX = 435
COL_UNIT_MAX = 525
COL_PRICE_MAX = 590

# Words within this many pts of each other vertically are on same visual row
ROW_Y_TOLERANCE = 4

SL_PATTERN = re.compile(r"^(\d{1,4})\.?$")
PRICE_PATTERN = re.compile(r"^[\d,]*\d+\.\d{1,3}$")


def cluster_words_into_rows(words):
    """Group words into visual rows by y-coordinate."""
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: w['top'])
    rows = []
    current_row = []
    current_top = None
    for w in sorted_words:
        if current_top is None or abs(w['top'] - current_top) <= ROW_Y_TOLERANCE:
            current_row.append(w)
            if current_top is None:
                current_top = w['top']
            else:
                current_top = min(current_top, w['top'])
        else:
            rows.append((current_top, current_row))
            current_row = [w]
            current_top = w['top']
    if current_row:
        rows.append((current_top, current_row))
    return rows


def is_serial_row(row_words):
    """Does this row contain a valid serial number in the slno column?"""
    for w in row_words:
        if w['x0'] < COL_SLNO_MAX:
            text = w['text'].rstrip('.')
            m = SL_PATTERN.match(text)
            if m:
                sl_no = int(m.group(1))
                if 1 <= sl_no <= 9999:
                    return sl_no
    return None


def assign_column(x):
    if x < COL_SLNO_MAX:
        return "slno"
    elif x < COL_DRUG_MAX:
        return "drug"
    elif x < COL_DOSAGE_MAX:
        return "dosage"
    elif x < COL_UNIT_MAX:
        return "unit"
    elif x < COL_PRICE_MAX:
        return "price"
    else:
        return "so"


def collect_entry_columns(entry_rows):
    cols = {"drug": [], "dosage": [], "unit": [], "price": [], "so": []}
    for row_top, row_words in entry_rows:
        sorted_row = sorted(row_words, key=lambda w: w['x0'])
        for w in sorted_row:
            col = assign_column(w['x0'])
            if col == "slno":
                continue
            cols[col].append(w['text'])
    return cols


def extract_clean_price(price_parts, so_parts):
    for token in price_parts + so_parts:
        cleaned = token.replace(",", "")
        if PRICE_PATTERN.match(cleaned):
            try:
                return float(cleaned)
            except ValueError:
                continue
    return None


def extract_so_notification(so_parts):
    text = " ".join(so_parts)
    m = re.search(r"S\.?\s*O\.?\s*\d{1,5}\s*\(E\)", text)
    if m:
        rest = text[m.end():]
        date_m = re.search(r"\d{1,2}\.\d{1,2}\.\d{2,4}", rest)
        if date_m:
            return f"{m.group(0)} {date_m.group(0)}"
        return m.group(0)
    return text.strip()


def parse_nppa_page(page, page_num):
    words = page.extract_words()
    if not words:
        return []

    rows = cluster_words_into_rows(words)
    anchors = []
    for i, (row_top, row_words) in enumerate(rows):
        sl_no = is_serial_row(row_words)
        if sl_no is not None:
            anchors.append((i, sl_no, row_top))

    if not anchors:
        return []

    entries = []
    for j, (anchor_idx, sl_no, anchor_top) in enumerate(anchors):
        next_anchor_idx = anchors[j + 1][0] if j + 1 < len(anchors) else len(rows)
        entry_rows = rows[anchor_idx:next_anchor_idx]
        cols = collect_entry_columns(entry_rows)

        drug_name = re.sub(r"\s+", " ", " ".join(cols["drug"])).strip()
        dosage = re.sub(r"\s+", " ", " ".join(cols["dosage"])).strip()

        entries.append({
            "sl_no": sl_no,
            "drug_name": drug_name,
            "dosage_form_strength": dosage,
            "unit": " ".join(cols["unit"]).strip(),
            "ceiling_price_inr": extract_clean_price(cols["price"], cols["so"]),
            "source_notification": extract_so_notification(cols["so"]),
            "_page": page_num,
        })

    return entries


def parse_nppa_pdf():
    if not INPUT_PDF.exists():
        raise FileNotFoundError(
            f"Could not find {INPUT_PDF}. "
            "Make sure you moved the PDF into data/raw/ and named it nppa_drugs_2025.pdf"
        )

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    all_entries = []

    print(f"Opening {INPUT_PDF} ...")
    with pdfplumber.open(INPUT_PDF) as pdf:
        print(f"Parsing pages 1-{MAIN_TABLE_LAST_PAGE} (main scheduled-drug table)...")
        for page_num, page in enumerate(pdf.pages[:MAIN_TABLE_LAST_PAGE], start=1):
            page_entries = parse_nppa_page(page, page_num)
            all_entries.extend(page_entries)
            if page_num % 10 == 0:
                print(f"  ...page {page_num}, entries so far: {len(all_entries)}")

    # Filter out any entries missing a price
    valid_entries = [e for e in all_entries if e["ceiling_price_inr"] is not None]
    dropped = len(all_entries) - len(valid_entries)

    print(f"\nExtracted {len(valid_entries)} valid NPPA scheduled-drug entries.")
    if dropped:
        print(f"Dropped {dropped} entries that lacked a parseable ceiling price.")

    # Build a search index by lowercased drug name
    index = {}
    for entry in valid_entries:
        key = entry["drug_name"].lower()
        index.setdefault(key, []).append(entry["sl_no"])

    output = {
        "entries": valid_entries,
        "index_by_drug_name_lc": index,
        "metadata": {
            "source": "NPPA Updated Price List as on 03.06.2025",
            "effective_from": "2025-04-01",
            "wpi_adjustment": "1.74028% over 2024",
            "regulatory_basis": "DPCO 2013, Schedule-I",
            "scope": (
                "Main scheduled-drug table (pages 1-37). Covers single-active-ingredient "
                "generic scheduled drugs, alphabetical 5-aminosalicylic Acid through "
                "approximately Clopidogrel. Manufacturer-specific brand combinations on "
                "later pages are out of v1 scope; commonly-billed generics not in this "
                "section are supplemented via nppa_common_supplement.json."
            ),
        },
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {OUTPUT_JSON}")
    print(f"Unique drug names in index: {len(index)}")

    # Sanity checks
    print("\nFirst 5 entries (sanity check):")
    for entry in valid_entries[:5]:
        print(f"  #{entry['sl_no']}: {entry['drug_name']} | "
              f"{entry['dosage_form_strength']} | "
              f"₹{entry['ceiling_price_inr']:.2f} per {entry['unit']}")

    print("\nSearching for common A-C hospital drugs:")
    for search in ["amlodipine", "amoxicillin", "atorvastatin", "aspirin",
                   "azithromycin", "acyclovir", "ceftriaxone", "cefuroxime",
                   "cetirizine", "ciprofloxacin"]:
        matches = [k for k in index if search in k]
        if matches:
            sample_key = matches[0]
            sample_sl = index[sample_key][0]
            sample = next(e for e in valid_entries if e["sl_no"] == sample_sl)
            print(f"  ✓ {search}: {len(matches)} key(s); e.g. {sample['dosage_form_strength']} → ₹{sample['ceiling_price_inr']:.2f}")
        else:
            print(f"  ✗ {search}: NO MATCHES (expected if alphabetically beyond scope)")


if __name__ == "__main__":
    parse_nppa_pdf()