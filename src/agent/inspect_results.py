import json
from pathlib import Path


RESULT_PATH = Path("data/uploaded/test_analysis_result.json")


def money(value):
    if value is None:
        return "₹0"
    try:
        return f"₹{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


def get_issue_type(issue):
    return (
        issue.get("type")
        or issue.get("issue_type")
        or issue.get("category")
        or "UNKNOWN_TYPE"
    )


def get_amount(issue):
    return (
        issue.get("amount_inr")
        or issue.get("overcharge_amount")
        or issue.get("overcharge")
        or issue.get("amount")
        or 0
    )


def get_description(issue):
    return issue.get("description") or issue.get("summary") or ""


def get_confidence(issue):
    return issue.get("confidence") or issue.get("confidence_level") or "UNKNOWN"


def get_evidence(issue):
    evidence = issue.get("evidence") or issue.get("evidence_list") or []

    if isinstance(evidence, list):
        return "; ".join(str(item) for item in evidence)

    return str(evidence)


def main():
    if not RESULT_PATH.exists():
        raise FileNotFoundError(f"Could not find {RESULT_PATH}")

    with open(RESULT_PATH, "r") as f:
        result = json.load(f)

    issues = result.get("issues", [])

    print("=" * 70)
    print("BillShield Analysis Result Inspection")
    print("=" * 70)
    print(f"Total issues: {len(issues)}")
    print()

    print("Top-level keys:")
    for key in result.keys():
        print(f"  - {key}")
    print()

    if issues:
        print("Issue schema keys:")
        for key in issues[0].keys():
            print(f"  - {key}")
        print()

    print("=" * 70)
    print("All Issues")
    print("=" * 70)

    for i, issue in enumerate(issues, 1):
        issue_id = issue.get("issue_id", f"ISSUE_{i:03d}")
        issue_type = get_issue_type(issue)
        description = get_description(issue)
        amount = get_amount(issue)
        confidence = get_confidence(issue)
        evidence = get_evidence(issue)

        print(f"{i}. {issue_id} - {issue_type}")
        print(f"   Description: {description}")
        print(f"   Amount: {money(amount)}")
        print(f"   Confidence: {confidence}")
        if evidence:
            print(f"   Evidence: {evidence}")
        print()

    print("=" * 70)
    print("Device / Stent Issues")
    print("=" * 70)

    found_device_issue = False

    for issue in issues:
        issue_type = get_issue_type(issue).lower()
        description = get_description(issue).lower()
        evidence = get_evidence(issue).lower()

        if (
            "device" in issue_type
            or "stent" in description
            or "stent" in evidence
            or "des" in description
            or "des" in evidence
            or "implant" in description
            or "implant" in evidence
        ):
            found_device_issue = True

            print(f"Issue ID: {issue.get('issue_id', 'UNKNOWN')}")
            print(f"Type: {get_issue_type(issue)}")
            print(f"Description: {get_description(issue)}")
            print(f"Amount: {money(get_amount(issue))}")
            print(f"Confidence: {get_confidence(issue)}")
            print(f"Evidence: {get_evidence(issue)}")
            print()

    if not found_device_issue:
        print("No device/stent issue found using description/evidence/type search.")
        print("This means either:")
        print("  1. The stent issue is described without the words stent/device/DES/implant, or")
        print("  2. The device checker did not emit a separate issue, or")
        print("  3. The issue schema stores line-item details somewhere else.")


if __name__ == "__main__":
    main()