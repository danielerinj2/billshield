"""
Parse the IRDAI Standard Non-Payable Items List into JSON.
"""

import json
import re
from collections import Counter
from pathlib import Path

import pdfplumber

INPUT_PDF = Path("data/raw/non_payable_items.pdf")
OUTPUT_JSON = Path("data/reference/non_payable_items.json")

ENTRY_START = re.compile(r"^\s*(\d{1,3})\s+(.+?)$")
SECTION_HEADER = re.compile(r"^\s+[A-Z][A-Z /,\(\)\"']{15,}$")
STATUS_KEYWORDS = ["Not Payable", "Not payable", "Non Payable", "Payable", "Essential"]


def split_name_and_status(line):
    for kw in STATUS_KEYWORDS:
        idx = line.find(kw)
        if idx > 0:
            return line[:idx].strip(), line[idx:].strip()
    parts = re.split(r"\s{2,}", line, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return line.strip(), ""


def classify_status(text):
    if not text:
        return "review_manually"
    lower = text.lower()
    has_essential = "essential" in lower or "may be considered" in lower or "payable as part" in lower
    has_not_payable = "not payable" in lower or "non-payable" in lower
    has_payable = "payable" in lower
    if has_not_payable and has_essential:
        return "conditionally_payable"
    if has_not_payable:
        return "not_payable"
    if has_essential:
        return "conditionally_payable"
    if has_payable:
        first_word = text.strip().split()[0].lower()
        if first_word.startswith("payable"):
            return "payable"
        return "conditionally_payable"
    return "review_manually"


def parse_non_payable():
    if not INPUT_PDF.exists():
        raise FileNotFoundError(f"Could not find {INPUT_PDF}")
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    full_text = ""
    with pdfplumber.open(INPUT_PDF) as pdf:
        for page in pdf.pages:
            full_text += (page.extract_text() or "") + "\n"
    items = []
    current = None
    for line in full_text.split("\n"):
        if not line.rstrip():
            continue
        m = ENTRY_START.match(line)
        if m and not SECTION_HEADER.match(line):
            sl_no = int(m.group(1))
            if 1 <= sl_no <= 300:
                if current is not None:
                    items.append(current)
                rest = m.group(2)
                name, status_text = split_name_and_status(rest)
                current = {"sl_no": sl_no, "item_name": name, "status_text_raw": status_text}
                continue
        if current is not None and not SECTION_HEADER.match(line):
            cont = line.strip()
            if cont:
                if not current["status_text_raw"]:
                    current["item_name"] += " " + cont
                else:
                    current["status_text_raw"] += " " + cont
    if current is not None:
        items.append(current)
    for item in items:
        item["status"] = classify_status(item["status_text_raw"])
        item["item_name"] = item["item_name"].strip()
        item["status_text_raw"] = item["status_text_raw"].strip()
    output = {
        "items": items,
        "metadata": {
            "source": "IRDAI Standard List of Non-Payable Items",
            "regulatory_basis": "IRDAI Master Circular on Health Insurance Business 2024",
        }
    }
    OUTPUT_JSON.write_text(json.dumps(output, indent=2))
    status_counts = Counter(i["status"] for i in items)
    print(f"Wrote {OUTPUT_JSON}")
    print(f"Total items parsed: {len(items)}")
    for s in ["not_payable", "conditionally_payable", "payable", "review_manually"]:
        print(f"  {s}: {status_counts.get(s, 0)}")
    print("\nFirst 10 items:")
    for item in items[:10]:
        print(f"  #{item['sl_no']:>3} {item['item_name'][:45]:<45} -> {item['status']}")


if __name__ == "__main__":
    parse_non_payable()