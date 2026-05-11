"""
Merge the parsed NPPA scheduled drugs (pages 1-37) with the hand-curated
common-drugs supplement into a unified lookup file.

Run from project root:
    python -m src.scripts.build_drug_lookup

Output: data/reference/drug_lookup.json
"""

import json
from pathlib import Path

PARSED_FILE = Path("data/reference/nppa_drugs.json")
SUPPLEMENT_FILE = Path("data/reference/nppa_common_supplement.json")
OUTPUT_FILE = Path("data/reference/drug_lookup.json")


def main():
    if not PARSED_FILE.exists():
        raise FileNotFoundError(f"Run parse_nppa_pdf.py first; {PARSED_FILE} not found")
    if not SUPPLEMENT_FILE.exists():
        raise FileNotFoundError(f"{SUPPLEMENT_FILE} not found — Stage B file missing")

    parsed = json.loads(PARSED_FILE.read_text())
    supplement = json.loads(SUPPLEMENT_FILE.read_text())

    # Unified entry schema
    unified = []

    # Add parsed entries
    for e in parsed["entries"]:
        unified.append({
            "drug_name": e["drug_name"],
            "synonyms": [],
            "dosage_form_strength": e["dosage_form_strength"],
            "unit": e["unit"],
            "ceiling_price_inr": e["ceiling_price_inr"],
            "source_notification": e["source_notification"],
            "data_source": "parsed_nppa_pages_1_to_37",
        })

    # Add supplement entries
    for e in supplement["entries"]:
        unified.append({
            "drug_name": e["drug_name"],
            "synonyms": e.get("synonyms", []),
            "dosage_form_strength": e["dosage_form_strength"],
            "unit": e["unit"],
            "ceiling_price_inr": e["ceiling_price_inr"],
            "source_notification": e["source_notification"],
            "data_source": "hand_curated_supplement",
        })

    # Build a comprehensive search index that includes synonyms
    name_index = {}
    for i, entry in enumerate(unified):
        keys = [entry["drug_name"].lower()]
        for syn in entry.get("synonyms", []):
            # Strip "(brand)" annotations from synonym keys
            clean_syn = syn.split("(")[0].strip().lower()
            if clean_syn:
                keys.append(clean_syn)
        for key in keys:
            name_index.setdefault(key, []).append(i)

    output = {
        "entries": unified,
        "name_index_lc": name_index,
        "metadata": {
            "total_entries": len(unified),
            "from_parsed_pdf": len(parsed["entries"]),
            "from_supplement": len(supplement["entries"]),
            "unique_search_keys": len(name_index),
            "compiled_from": [
                "data/reference/nppa_drugs.json",
                "data/reference/nppa_common_supplement.json",
            ],
            "usage": (
                "Look up by lowercased drug name in 'name_index_lc'. Each value is "
                "a list of indices into 'entries'. Synonyms are pre-expanded into "
                "the index. The agent's drug-lookup tool should normalize input "
                "(strip whitespace, lowercase) before querying."
            ),
        },
    }

    OUTPUT_FILE.write_text(json.dumps(output, indent=2))

    print(f"Wrote {OUTPUT_FILE}")
    print(f"  Total entries: {len(unified)}")
    print(f"  From parsed PDF: {len(parsed['entries'])}")
    print(f"  From supplement: {len(supplement['entries'])}")
    print(f"  Unique search keys (incl. synonyms): {len(name_index)}")

    # Verification: test the lookups that previously failed
    print("\nVerification — drugs that were missing before:")
    for test_drug in ["paracetamol", "acetaminophen", "metformin", "ondansetron",
                      "pantoprazole", "metronidazole", "tramadol", "enoxaparin",
                      "ceftriaxone", "cefuroxime", "ciprofloxacin", "aspirin"]:
        if test_drug in name_index:
            indices = name_index[test_drug]
            sample = unified[indices[0]]
            print(f"  ✓ {test_drug}: {len(indices)} form(s); e.g. "
                  f"'{sample['drug_name']}' {sample['dosage_form_strength']} → "
                  f"₹{sample['ceiling_price_inr']:.2f} [{sample['data_source']}]")
        else:
            # Check if it's in the parsed file under another name (e.g. Aspirin = Acetylsalicylic acid)
            matches = [i for i, e in enumerate(unified) if test_drug in e["drug_name"].lower()]
            if matches:
                sample = unified[matches[0]]
                print(f"  ~ {test_drug}: found via substring; "
                      f"'{sample['drug_name']}' → ₹{sample['ceiling_price_inr']:.2f}")
            else:
                print(f"  ✗ {test_drug}: STILL MISSING")


if __name__ == "__main__":
    main()