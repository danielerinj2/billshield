"""
Parse hospital discharge summary PDFs into structured JSON.

Handles digital PDFs with selectable text. Uses regex-first extraction
for structured fields, leaves narrative sections as raw text for
optional LLM-assisted enrichment later.

Output: structured discharge data for downstream agent consumption.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pdfplumber


# --- Patient information patterns ---
PATIENT_PATTERNS = {
    "name": r"patient\s*name[:\s]+([A-Z][A-Za-z\s.]+?)(?:\s{2,}|age|sex|$)",
    "age_sex": r"age\s*/?\s*sex[:\s]+([0-9]+\s*(?:Years?|Yrs?)?\s*/?\s*(?:Male|Female|M|F))",
    "mrn": r"MRN\s*/?\s*Patient\s*ID[:\s]+([A-Z]{2,}[\-/][A-Z0-9\-/]+)",
    "bill_number": r"bill\s*number[:\s]+([A-Z0-9\-/]+)",
    "admission_date": r"admission\s*date[:\s]*([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4})",
    "discharge_date": r"discharge\s*date[:\s]*([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4})",
    "length_of_stay": r"length\s*of\s*stay[:\s]+([0-9]+\s*days?)",
    "wards_text": r"wards?\s*\(?s?\)?[:\s]+([^\n]+?)(?:\s{2,}|$)",
    "consultant": r"consultant[:\s]+([^\n]+?)(?:\s{2,}|$|attending)",
    "attending_surgeon": r"attending\s*surgeon[:\s]+([^\n]+?)(?:\s{2,}|$)",
}


def parse_age_sex(age_sex_str: Optional[str]) -> dict[str, Any]:
    """Parse '45 Years / Male' into structured fields."""
    if not age_sex_str:
        return {"age": None, "sex": None}

    age_match = re.search(r"(\d+)", age_sex_str)
    sex_match = re.search(r"(Male|Female|M|F)\b", age_sex_str, re.IGNORECASE)

    age = int(age_match.group(1)) if age_match else None
    sex_raw = sex_match.group(1) if sex_match else None
    sex = {"m": "Male", "f": "Female"}.get(sex_raw.lower()[0], sex_raw) if sex_raw else None

    return {"age": age, "sex": sex}


def parse_length_of_stay(los_str: Optional[str]) -> Optional[int]:
    """Parse '7 days' -> 7."""
    if not los_str:
        return None
    match = re.search(r"(\d+)", los_str)
    return int(match.group(1)) if match else None


def parse_wards(wards_str: Optional[str]) -> list[dict[str, Any]]:
    """Parse 'ICU (3d), Private Deluxe (4d)' into a list of ward dicts."""
    if not wards_str:
        return []

    wards = []
    # Match patterns like "ICU (3d)", "Private Deluxe (4d)", "General Ward (5 days)"
    for match in re.finditer(r"([A-Za-z][A-Za-z\s]+?)\s*\(\s*(\d+)\s*(?:d|days?)\s*\)", wards_str):
        ward_type = match.group(1).strip()
        duration = int(match.group(2))
        wards.append({
            "type": ward_type,
            "duration_days": duration
        })

    return wards


def extract_patient_info(text: str) -> dict[str, Any]:
    """Extract patient information from the discharge summary."""
    patient_info = {}

    for field, pattern in PATIENT_PATTERNS.items():
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        patient_info[field] = match.group(1).strip() if match else None

    # Parse age/sex into structured fields
    age_sex = parse_age_sex(patient_info.pop("age_sex", None))
    patient_info.update(age_sex)

    # Parse length of stay
    patient_info["length_of_stay_days"] = parse_length_of_stay(
        patient_info.pop("length_of_stay", None)
    )

    # Parse wards
    patient_info["wards"] = parse_wards(patient_info.pop("wards_text", None))

    return patient_info


def extract_diagnoses(text: str) -> dict[str, Any]:
    """Extract primary and secondary diagnoses with ICD-10 codes where present."""
    diagnoses = {
        "primary": None,
        "primary_icd10": None,
        "secondary": []
    }

    # Locate the FINAL DIAGNOSIS section
    diag_section_match = re.search(
        r"FINAL\s*DIAGNOSIS\s*(.+?)(?=PROCEDURES?\s*PERFORMED|CLINICAL\s*COURSE|HOSPITAL\s*STAY|$)",
        text, re.IGNORECASE | re.DOTALL
    )
    if not diag_section_match:
        return diagnoses

    diag_text = diag_section_match.group(1)

   # Primary diagnosis - find text after "Primary:" up to ICD-10 or Secondary
    primary_match = re.search(
        r"Primary[:\s]+(.+?)(?:\s*ICD-?10[:\s]*([A-Z]?\d{1,3}(?:\.\d{1,3})?))?\s*(?:Secondary|$)",
        diag_text, re.IGNORECASE | re.DOTALL
    )
    if primary_match:
        primary_text = primary_match.group(1).strip()
        primary_text = re.sub(r"\s*ICD-?10.*$", "", primary_text, flags=re.IGNORECASE)
        primary_text = re.sub(r"\s+", " ", primary_text).strip().rstrip(".")
        diagnoses["primary"] = primary_text
        if primary_match.group(2):
            diagnoses["primary_icd10"] = primary_match.group(2).strip()

    # Fallback: extract ICD-10 separately if the combined regex missed it
    if diagnoses["primary"] and not diagnoses["primary_icd10"]:
        # Look for ICD-10 near the primary diagnosis text
        icd_match = re.search(
            r"Primary[^.]*?ICD-?10[:\s]*([A-Z]?\d{1,3}(?:\.\d{1,3})?)",
            diag_text, re.IGNORECASE | re.DOTALL
        )
        if icd_match:
            diagnoses["primary_icd10"] = icd_match.group(1).strip()

    # Secondary diagnoses (bullet points)
    secondary_section_match = re.search(
        r"Secondary[:\s]*(.+?)$",
        diag_text, re.IGNORECASE | re.DOTALL
    )
    if secondary_section_match:
        secondary_text = secondary_section_match.group(1)
        # Each secondary diagnosis with optional ICD-10
        for line_match in re.finditer(
            r"[•\-\*]?\s*([A-Z][^•\n\(]+?)(?:\s*\(ICD-?10[:\s]*([A-Z]?\d{1,3}(?:\.\d{1,3})?)\))?(?=\s*[•\-\*\n]|$)",
            secondary_text
        ):
            diag_name = line_match.group(1).strip().rstrip(",.;")
            diag_name = re.sub(r"\s+", " ", diag_name)
            if len(diag_name) < 5 or diag_name.lower() in ["icd", "icd-10"]:
                continue
            entry = {"diagnosis": diag_name}
            if line_match.group(2):
                entry["icd10"] = line_match.group(2).strip()
            diagnoses["secondary"].append(entry)

    return diagnoses


def extract_procedures(text: str) -> list[dict[str, Any]]:
    """Extract procedures performed from the discharge summary."""
    procedures = []

    # Locate the PROCEDURES PERFORMED section
    proc_section_match = re.search(
        r"PROCEDURES?\s*PERFORMED\s*(.+?)(?=CLINICAL\s*COURSE|HOSPITAL\s*STAY|DISCHARGE\s*MEDICATIONS|$)",
        text, re.IGNORECASE | re.DOTALL
    )
    if not proc_section_match:
        return procedures

    proc_text = proc_section_match.group(1)

    # Match numbered procedures: "1. Procedure Name ... Date: DD/MM/YYYY"
    # Procedures may not have explicit newlines between them in PDF extraction
    proc_blocks = re.split(r"(?:^|\s)(\d+)\.\s+", proc_text)

    # First element is text before "1.", skip it. Then iterate in pairs (number, content)
    for i in range(1, len(proc_blocks) - 1, 2):
        block_num = proc_blocks[i]
        block_content = proc_blocks[i + 1]

        # Procedure name is the first line / first phrase
        name_match = re.match(r"([^\n]+?)(?:\s*Date:|\s*\n|$)", block_content)
        name = name_match.group(1).strip() if name_match else ""
        name = re.sub(r"\s+", " ", name).rstrip(".")

        # Date
        date_match = re.search(
            r"Date[:\s]+([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4})",
            block_content
        )
        date = date_match.group(1) if date_match else None

        # Performed by
        performer_match = re.search(
            r"Performed\s*by[:\s]+([^\n|]+?)(?:\s{2,}|\n|$|\|)",
            block_content
        )
        performed_by = performer_match.group(1).strip() if performer_match else None

        # Any additional notes (everything after the date/performer lines)
        notes_text = block_content
        notes_text = re.sub(r"Date[:\s]+[0-9/\-]+\s*\|?\s*Performed\s*by[:\s]+[^\n]+\n?", "", notes_text, flags=re.IGNORECASE)
        notes_text = re.sub(r"Date[:\s]+[0-9/\-]+\n?", "", notes_text, flags=re.IGNORECASE)
        notes_text = re.sub(r"Performed\s*by[:\s]+[^\n]+\n?", "", notes_text, flags=re.IGNORECASE)
        # Remove the procedure name itself from notes
        if name:
            notes_text = notes_text.replace(name, "", 1)
        notes = re.sub(r"\s+", " ", notes_text).strip().rstrip(".")
        notes = notes if notes else None

        if name:
            procedures.append({
                "name": name,
                "date": date,
                "performed_by": performed_by,
                "notes": notes
            })

    return procedures


def extract_medications(text: str) -> list[dict[str, Any]]:
    """Extract discharge medications."""
    medications = []

    med_section_match = re.search(
        r"DISCHARGE\s*MEDICATIONS\s*(.+?)(?=CONDITION\s*AT\s*DISCHARGE|FOLLOW-?UP|$)",
        text, re.IGNORECASE | re.DOTALL
    )
    if not med_section_match:
        return medications

    med_text = med_section_match.group(1)

    # Match lines like "1. Tab. Aspirin 75mg Once daily Lifelong"
    for line_match in re.finditer(
        r"(\d+)\.\s+([A-Z][A-Za-z.]*\.?\s*[A-Z][A-Za-z\s\-]+?\s*\d+\s*(?:mg|g|ml|mcg|IU|units?))\s+(.+?)(?=\n\s*\d+\.|$)",
        med_text, re.MULTILINE | re.DOTALL
    ):
        med_full = line_match.group(2).strip()
        remaining = line_match.group(3).strip()
        remaining = re.sub(r"\s+", " ", remaining)  # normalize whitespace

        # Duration indicators - the last word(s) usually indicate duration
        # Try matching common duration patterns at the end
        duration_pattern = r"\s+(Lifelong|Continue|\d+\s*(?:month|week|day|year)s?|Review.*$|As needed.*$)\s*$"
        duration_match = re.search(duration_pattern, remaining, re.IGNORECASE)

        if duration_match:
            duration = duration_match.group(1).strip()
            frequency = remaining[:duration_match.start()].strip().rstrip(",")
        else:
            frequency = remaining
            duration = None

        medications.append({
            "drug": med_full,
            "frequency": frequency,
            "duration": duration
        })

    return medications


def extract_narrative_sections(text: str) -> dict[str, str]:
    """Extract narrative prose sections as raw text for later LLM enrichment."""
    sections = {}

    section_patterns = {
        "clinical_course": r"CLINICAL\s*COURSE\s*/?\s*HOSPITAL\s*STAY\s*(.+?)(?=DISCHARGE\s*MEDICATIONS|CONDITION\s*AT\s*DISCHARGE|FOLLOW-?UP|$)",
        "condition_at_discharge": r"CONDITION\s*AT\s*DISCHARGE\s*(.+?)(?=FOLLOW-?UP|$)",
        "follow_up": r"FOLLOW-?UP\s*INSTRUCTIONS\s*(.+?)(?=_{3,}|Dr\.\s+[A-Z][a-z]+\s+[A-Z][a-z]+,\s*MD|$)",
    }

    for key, pattern in section_patterns.items():
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            section_text = match.group(1).strip()
            section_text = re.sub(r"\s+", " ", section_text)
            sections[key] = section_text

    return sections


def parse_discharge_pdf(pdf_path: str | Path) -> dict[str, Any]:
    """Main entry point: parse a discharge summary PDF into structured JSON."""
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"Discharge PDF not found: {pdf_path}")

    with pdfplumber.open(pdf_path) as pdf:
        full_text = ""
        for page in pdf.pages:
            full_text += (page.extract_text() or "") + "\n"

    patient = extract_patient_info(full_text)
    diagnoses = extract_diagnoses(full_text)
    procedures = extract_procedures(full_text)
    medications = extract_medications(full_text)
    narrative = extract_narrative_sections(full_text)

    return {
        "metadata": {
            "source_file": pdf_path.name,
            "parsed_at": datetime.now().isoformat(),
            "parser_version": "1.0",
        },
        "patient": patient,
        "diagnoses": diagnoses,
        "procedures": procedures,
        "discharge_medications": medications,
        "narrative_sections": narrative,
        "summary": {
            "procedure_count": len(procedures),
            "medication_count": len(medications),
            "secondary_diagnosis_count": len(diagnoses.get("secondary", [])),
            "narrative_sections_found": list(narrative.keys()),
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
        print("Usage: python -m src.scripts.parse_discharge_pdf <path_to_discharge.pdf>")
        print("Example: python -m src.scripts.parse_discharge_pdf data/samples/test_discharge_ankit.pdf")
        sys.exit(1)

    discharge_path = Path(sys.argv[1])
    print(f"Parsing: {discharge_path}")
    print("-" * 60)

    result = parse_discharge_pdf(discharge_path)

    # Print structured summary
    print("\nPATIENT INFORMATION:")
    for k, v in result["patient"].items():
        status = "✓" if v else "✗"
        v_display = v if v else "(not found)"
        print(f"  {status} {k:<22} {v_display}")

    print(f"\nDIAGNOSES:")
    print(f"  Primary: {result['diagnoses']['primary']}")
    if result['diagnoses']['primary_icd10']:
        print(f"    ICD-10: {result['diagnoses']['primary_icd10']}")
    print(f"  Secondary: {result['summary']['secondary_diagnosis_count']} found")
    for d in result['diagnoses']['secondary']:
        icd = f" ({d['icd10']})" if d.get('icd10') else ""
        print(f"    • {d['diagnosis']}{icd}")

    print(f"\nPROCEDURES: {result['summary']['procedure_count']} found")
    for i, p in enumerate(result['procedures'], 1):
        print(f"  {i}. {p['name']}")
        if p.get('date'):
            print(f"     Date: {p['date']}")
        if p.get('performed_by'):
            print(f"     Performed by: {p['performed_by']}")
        if p.get('notes'):
            print(f"     Notes: {p['notes'][:80]}{'...' if len(p['notes']) > 80 else ''}")

    print(f"\nDISCHARGE MEDICATIONS: {result['summary']['medication_count']} found")
    for i, m in enumerate(result['discharge_medications'], 1):
        print(f"  {i}. {m['drug']} | {m['frequency']} | {m['duration']}")

    print(f"\nNARRATIVE SECTIONS: {len(result['summary']['narrative_sections_found'])} extracted")
    for section_name in result['summary']['narrative_sections_found']:
        section_len = len(result['narrative_sections'][section_name])
        print(f"  • {section_name} ({section_len} chars)")

    output_path = _save_output(result, discharge_path)
    print(f"\nSaved to: {output_path}")