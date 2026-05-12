"""
Multi-procedure billing and settlement timeline detection for BillShield.

This module adds rule-based checks on top of the RAG/benchmark engine.

Rules covered:
1. Multi-procedure billing discount:
   - Primary/highest-cost procedure: 100%
   - Second procedure: 50%
   - Third and later procedures: 25%

2. Settlement / authorization timeline hints:
   - Pre-authorization: 1 hour
   - Final authorization: 3 hours
   - Complaint resolution: 14 days

The functions return issues in the same schema used by BillShield:
{
    "issue_id": "...",
    "issue_type": "...",
    "description": "...",
    "billed_amount": ...,
    "benchmark_amount": ...,
    "overcharge_amount": ...,
    "confidence": "...",
    "evidence": [...],
    "action_required": "..."
}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CAPSTONE_RULES_PATH = Path("data/reference/capstone_rules.json")


DEFAULT_MULTI_PROCEDURE_RULE = {
    "rule_name": "Multi-Procedure Billing Discount",
    "description": (
        "When multiple procedures are performed in one OT/session, "
        "the primary/highest-cost procedure is billed at 100%, "
        "the second at 50%, and the third and subsequent procedures at 25%."
    ),
    "source": "capstone_verification_rules.pdf",
    "discounts": [
        {
            "position": "primary",
            "percentage": 100,
            "description": "Highest cost procedure",
        },
        {
            "position": "second",
            "percentage": 50,
            "description": "Second procedure in same session",
        },
        {
            "position": "third_and_beyond",
            "percentage": 25,
            "description": "Third and subsequent procedures",
        },
    ],
    "violation_type": "unbundled_charges",
    "evidence_required": "Multiple procedures billed at full value in same OT/session",
}


DEFAULT_TIMELINE_RULES = [
    {
        "rule_name": "Cashless Pre-Authorization Timeline",
        "requirement": "Insurer should process cashless pre-authorization within 1 hour.",
        "timeline_minutes": 60,
        "source": "IRDAI Master Circular / capstone rules",
    },
    {
        "rule_name": "Final Authorization Timeline",
        "requirement": "Insurer should process final authorization within 3 hours of discharge request.",
        "timeline_minutes": 180,
        "source": "IRDAI Master Circular / capstone rules",
    },
    {
        "rule_name": "Complaint Resolution Timeline",
        "requirement": "Insurer should resolve complaints within 14 days.",
        "timeline_days": 14,
        "source": "IRDAI grievance rules / capstone rules",
    },
]


def load_capstone_rules(path: Path = CAPSTONE_RULES_PATH) -> dict[str, Any]:
    """
    Load capstone rules from JSON.

    Falls back to default in-code rules if the JSON file is missing or malformed.
    This prevents the agent from crashing during demos.
    """
    if not path.exists():
        return {
            "multi_procedure_billing": DEFAULT_MULTI_PROCEDURE_RULE,
            "timeline_requirements": DEFAULT_TIMELINE_RULES,
        }

    try:
        with path.open("r", encoding="utf-8") as file:
            rules = json.load(file)
    except (json.JSONDecodeError, OSError):
        return {
            "multi_procedure_billing": DEFAULT_MULTI_PROCEDURE_RULE,
            "timeline_requirements": DEFAULT_TIMELINE_RULES,
        }

    if "multi_procedure_billing" not in rules:
        rules["multi_procedure_billing"] = DEFAULT_MULTI_PROCEDURE_RULE

    if "timeline_requirements" not in rules:
        rules["timeline_requirements"] = DEFAULT_TIMELINE_RULES

    return rules


def detect_multi_procedure_violations(
    bill_data: dict[str, Any],
    discharge_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Detect possible overbilling when multiple procedures are performed in one session.

    Expected billing rule:
    - Highest-cost procedure: 100%
    - Second procedure: 50%
    - Third and subsequent procedures: 25%

    Args:
        bill_data: Parsed bill JSON.
        discharge_data: Parsed discharge summary JSON.

    Returns:
        List of issue dictionaries.
    """
    rules = load_capstone_rules()
    multi_proc_rule = rules.get(
        "multi_procedure_billing",
        DEFAULT_MULTI_PROCEDURE_RULE,
    )

    issues: list[dict[str, Any]] = []

    discharge_procedures = _extract_discharge_procedures(discharge_data)

    if len(discharge_procedures) < 2:
        return issues

    bill_items = _extract_bill_items(bill_data)
    procedure_charges = _find_procedure_charges(bill_items, discharge_procedures)

    if len(procedure_charges) < 2:
        return issues

    procedure_charges.sort(key=lambda item: item["amount"], reverse=True)

    total_billed = sum(item["amount"] for item in procedure_charges)
    total_expected = _calculate_expected_charges(procedure_charges)
    overcharge = total_billed - total_expected

    if overcharge <= 100:
        return issues

    evidence = _build_multi_procedure_evidence(
        procedure_charges=procedure_charges,
        total_billed=total_billed,
        total_expected=total_expected,
        overcharge=overcharge,
        source=str(multi_proc_rule.get("source", "capstone_verification_rules.pdf")),
    )

    issues.append(
        {
            "issue_id": f"MULTI_PROC_{len(procedure_charges):03d}",
            "issue_type": "unbundled_charges",
            "description": (
                f"{len(procedure_charges)} procedures appear to be billed without "
                "multi-procedure discounting. Only the primary procedure should be "
                "billed at 100%; the second should be 50%, and third/subsequent "
                "procedures should be 25%."
            ),
            "billed_amount": round(total_billed, 2),
            "benchmark_amount": round(total_expected, 2),
            "overcharge_amount": round(overcharge, 2),
            "confidence": "high",
            "evidence": evidence,
            "action_required": (
                "Challenge multi-procedure billing and request recalculation using "
                "100% / 50% / 25% procedure discounting."
            ),
        }
    )

    return issues


def validate_settlement_timelines(
    rejection_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Detect possible insurer timeline violations from rejection/claim metadata.

    This function supports two modes:
    1. Structured fields, if available:
       - preauth_delay_minutes
       - final_authorization_delay_minutes
       - complaint_resolution_days

    2. Keyword hints inside rejection reasons:
       - delay
       - pending
       - waiting
       - processing time
       - authorization delayed
    """
    rules = load_capstone_rules()
    timeline_rules = rules.get("timeline_requirements", DEFAULT_TIMELINE_RULES)

    issues: list[dict[str, Any]] = []

    issues.extend(_check_structured_timeline_fields(rejection_data, timeline_rules))
    issues.extend(_check_timeline_keywords(rejection_data, timeline_rules))

    return _deduplicate_issues(issues)


def _extract_discharge_procedures(discharge_data: dict[str, Any]) -> list[str]:
    """
    Extract procedure names from discharge data using flexible schema handling.
    """
    candidates = (
        discharge_data.get("procedures_performed")
        or discharge_data.get("procedures")
        or discharge_data.get("procedure_list")
        or []
    )

    if isinstance(candidates, str):
        return [candidates]

    procedures: list[str] = []

    if isinstance(candidates, list):
        for item in candidates:
            if isinstance(item, str):
                procedures.append(item)
            elif isinstance(item, dict):
                name = (
                    item.get("name")
                    or item.get("procedure")
                    or item.get("description")
                    or item.get("procedure_name")
                )
                if name:
                    procedures.append(str(name))

    return [procedure for procedure in procedures if procedure.strip()]


def _extract_bill_items(bill_data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extract line items from bill data using flexible schema handling.
    """
    candidates = (
        bill_data.get("line_items")
        or bill_data.get("items")
        or bill_data.get("bill_items")
        or []
    )

    if not isinstance(candidates, list):
        return []

    return [item for item in candidates if isinstance(item, dict)]


def _find_procedure_charges(
    bill_items: list[dict[str, Any]],
    discharge_procedures: list[str],
) -> list[dict[str, Any]]:
    """
    Match bill line items to likely procedure/surgery charges.
    """
    procedure_charges: list[dict[str, Any]] = []

    procedure_keywords = [
        "surgery",
        "procedure",
        "angioplasty",
        "stent placement",
        "bypass",
        "valve replacement",
        "implant surgery",
        "ot charges",
        "ot charge",
        "operation",
        "operation theatre",
        "surgical",
        "laparoscopy",
        "endoscopy",
        "arthroscopy",
        "cath lab",
        "cathlab",
    ]

    discharge_keywords = _build_keywords_from_discharge(discharge_procedures)

    for item in bill_items:
        description = _get_item_description(item)
        amount = _get_item_amount(item)

        if amount <= 0:
            continue

        lower_description = description.lower()

        has_procedure_keyword = any(
            keyword in lower_description for keyword in procedure_keywords
        )

        matches_discharge_procedure = any(
            keyword in lower_description for keyword in discharge_keywords
        )

        if has_procedure_keyword or matches_discharge_procedure:
            procedure_charges.append(
                {
                    "name": description or "Unknown procedure",
                    "amount": amount,
                    "item_data": item,
                }
            )

    return procedure_charges


def _build_keywords_from_discharge(discharge_procedures: list[str]) -> list[str]:
    """
    Create lightweight matching keywords from discharge procedure names.
    """
    stopwords = {
        "with",
        "and",
        "the",
        "for",
        "left",
        "right",
        "under",
        "general",
        "local",
        "anaesthesia",
        "anesthesia",
        "procedure",
        "surgery",
    }

    keywords: set[str] = set()

    for procedure in discharge_procedures:
        words = procedure.lower().replace("/", " ").replace("-", " ").split()

        for word in words:
            clean_word = "".join(char for char in word if char.isalnum())

            if len(clean_word) >= 5 and clean_word not in stopwords:
                keywords.add(clean_word)

    return sorted(keywords)


def _get_item_description(item: dict[str, Any]) -> str:
    """
    Read item description from common bill parser field names.
    """
    value = (
        item.get("description")
        or item.get("item_description")
        or item.get("item_name")
        or item.get("name")
        or ""
    )

    return str(value).strip()


def _get_item_amount(item: dict[str, Any]) -> float:
    """
    Read billed amount from common bill parser field names.
    """
    value = (
        item.get("amount")
        or item.get("total")
        or item.get("billed_amount")
        or item.get("line_total")
        or item.get("net_amount")
        or 0
    )

    try:
        return float(str(value).replace(",", "").replace("₹", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _calculate_expected_charges(procedure_charges: list[dict[str, Any]]) -> float:
    """
    Calculate expected multi-procedure charge using 100% / 50% / 25% logic.
    """
    if not procedure_charges:
        return 0.0

    expected = 0.0

    for index, procedure in enumerate(procedure_charges):
        amount = procedure["amount"]

        if index == 0:
            expected += amount
        elif index == 1:
            expected += amount * 0.5
        else:
            expected += amount * 0.25

    return expected


def _build_multi_procedure_evidence(
    procedure_charges: list[dict[str, Any]],
    total_billed: float,
    total_expected: float,
    overcharge: float,
    source: str,
) -> list[str]:
    """
    Build readable evidence strings for the multi-procedure issue.
    """
    evidence = [
        f"Procedure charges detected: {len(procedure_charges)}",
        f"Total billed for detected procedures: ₹{total_billed:,.0f}",
        f"Expected charge after multi-procedure discounting: ₹{total_expected:,.0f}",
        f"Potential overcharge: ₹{overcharge:,.0f}",
    ]

    for index, procedure in enumerate(procedure_charges):
        if index == 0:
            expected = procedure["amount"]
            discount_label = "Primary procedure at 100%"
        elif index == 1:
            expected = procedure["amount"] * 0.5
            discount_label = "Second procedure should be 50%"
        else:
            expected = procedure["amount"] * 0.25
            discount_label = "Third/subsequent procedure should be 25%"

        evidence.append(
            f"{discount_label}: {procedure['name']} | "
            f"Billed ₹{procedure['amount']:,.0f}, expected ₹{expected:,.0f}"
        )

    evidence.append(f"Source: {source}")

    return evidence


def _check_structured_timeline_fields(
    rejection_data: dict[str, Any],
    timeline_rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Check structured timeline fields if the parser provides them.
    """
    issues: list[dict[str, Any]] = []

    preauth_delay = _safe_float(rejection_data.get("preauth_delay_minutes"))
    final_auth_delay = _safe_float(
        rejection_data.get("final_authorization_delay_minutes")
    )
    complaint_days = _safe_float(rejection_data.get("complaint_resolution_days"))

    if preauth_delay is not None and preauth_delay > 60:
        issues.append(
            {
                "issue_id": "TIMELINE_PREAUTH_DELAY",
                "issue_type": "rejection_delayed",
                "description": (
                    "Cashless pre-authorization appears delayed beyond the "
                    "1-hour timeline."
                ),
                "billed_amount": 0,
                "benchmark_amount": 60,
                "overcharge_amount": 0,
                "confidence": "high",
                "evidence": [
                    f"Observed pre-authorization delay: {preauth_delay:.0f} minutes",
                    "Expected timeline: 60 minutes",
                    _timeline_source(timeline_rules),
                ],
                "action_required": (
                    "Raise timeline violation with insurer and request written "
                    "explanation for pre-authorization delay."
                ),
            }
        )

    if final_auth_delay is not None and final_auth_delay > 180:
        issues.append(
            {
                "issue_id": "TIMELINE_FINAL_AUTH_DELAY",
                "issue_type": "rejection_delayed",
                "description": (
                    "Final authorization appears delayed beyond the 3-hour timeline."
                ),
                "billed_amount": 0,
                "benchmark_amount": 180,
                "overcharge_amount": 0,
                "confidence": "high",
                "evidence": [
                    f"Observed final authorization delay: {final_auth_delay:.0f} minutes",
                    "Expected timeline: 180 minutes",
                    _timeline_source(timeline_rules),
                ],
                "action_required": (
                    "Raise timeline violation with insurer and request waiver of "
                    "delay-related hospital charges, if any."
                ),
            }
        )

    if complaint_days is not None and complaint_days > 14:
        issues.append(
            {
                "issue_id": "TIMELINE_COMPLAINT_DELAY",
                "issue_type": "rejection_delayed",
                "description": (
                    "Complaint resolution appears delayed beyond the 14-day timeline."
                ),
                "billed_amount": 0,
                "benchmark_amount": 14,
                "overcharge_amount": 0,
                "confidence": "high",
                "evidence": [
                    f"Observed complaint resolution time: {complaint_days:.0f} days",
                    "Expected timeline: 14 days",
                    _timeline_source(timeline_rules),
                ],
                "action_required": (
                    "Escalate delayed complaint resolution through insurer grievance "
                    "channel and IRDAI/Bima Bharosa if unresolved."
                ),
            }
        )

    return issues


def _check_timeline_keywords(
    rejection_data: dict[str, Any],
    timeline_rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Detect possible timeline issues from free-text rejection reasons.
    """
    reasons = _extract_rejection_reasons(rejection_data)
    issues: list[dict[str, Any]] = []

    delay_keywords = [
        "delay",
        "delayed",
        "pending",
        "waiting",
        "processing time",
        "authorization delayed",
        "authorisation delayed",
        "preauth delayed",
        "pre-auth delayed",
        "final authorization delayed",
        "final authorisation delayed",
    ]

    for reason in reasons:
        lower_reason = reason.lower()

        if any(keyword in lower_reason for keyword in delay_keywords):
            issues.append(
                {
                    "issue_id": "TIMELINE_DELAY",
                    "issue_type": "rejection_delayed",
                    "description": (
                        "Claim or authorization may have been delayed beyond "
                        "applicable timeline requirements."
                    ),
                    "billed_amount": 0,
                    "benchmark_amount": 0,
                    "overcharge_amount": 0,
                    "confidence": "medium",
                    "evidence": [
                        "Delay-related language found in rejection/claim notes",
                        f"Text: {reason}",
                        "Expected timelines include 1-hour pre-authorization, "
                        "3-hour final authorization, and 14-day complaint resolution.",
                        _timeline_source(timeline_rules),
                    ],
                    "action_required": (
                        "Ask insurer for exact timestamps and challenge any delay "
                        "beyond regulatory timelines."
                    ),
                }
            )
            break

    return issues


def _extract_rejection_reasons(rejection_data: dict[str, Any]) -> list[str]:
    """
    Extract rejection reason text from flexible schemas.
    """
    raw_reasons = (
        rejection_data.get("rejection_reasons")
        or rejection_data.get("reasons")
        or rejection_data.get("denial_reasons")
        or []
    )

    if isinstance(raw_reasons, str):
        return [raw_reasons]

    reasons: list[str] = []

    if isinstance(raw_reasons, list):
        for item in raw_reasons:
            if isinstance(item, str):
                reasons.append(item)
            elif isinstance(item, dict):
                reason = (
                    item.get("reason")
                    or item.get("description")
                    or item.get("text")
                    or item.get("rejection_reason")
                )
                if reason:
                    reasons.append(str(reason))

    return [reason for reason in reasons if reason.strip()]


def _timeline_source(timeline_rules: list[dict[str, Any]]) -> str:
    """
    Return a compact source string for timeline evidence.
    """
    if not timeline_rules:
        return "Source: capstone timeline rules"

    sources = {
        str(rule.get("source", "")).strip()
        for rule in timeline_rules
        if rule.get("source")
    }

    if not sources:
        return "Source: capstone timeline rules"

    return "Source: " + "; ".join(sorted(sources))


def _safe_float(value: Any) -> float | None:
    """
    Safely convert values like '1,200', '₹1200', or 1200 into float.
    """
    if value is None:
        return None

    try:
        return float(str(value).replace(",", "").replace("₹", "").strip())
    except (TypeError, ValueError):
        return None


def _deduplicate_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Remove duplicate issues by issue_id.
    """
    seen: set[str] = set()
    unique_issues: list[dict[str, Any]] = []

    for issue in issues:
        issue_id = str(issue.get("issue_id", ""))

        if issue_id in seen:
            continue

        seen.add(issue_id)
        unique_issues.append(issue)

    return unique_issues