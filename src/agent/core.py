"""
BillShield Agent Core - SPAOR orchestrator for bill analysis.
"""

import json
from typing import Dict, List, Any
from dataclasses import dataclass, asdict
from enum import Enum

from src.agent.multi_procedure_detection import (
    detect_multi_procedure_violations,
    validate_settlement_timelines,
)


class IssueType(Enum):
    """Types of billing issues the agent can detect."""
    PROCEDURE_OVERCHARGE = "procedure_overcharge"
    DRUG_OVERCHARGE = "drug_overcharge"
    DEVICE_OVERCHARGE = "device_overcharge"
    NON_PAYABLE_ITEM = "non_payable_item"
    DUPLICATE_BILLING = "duplicate_billing"
    UNBUNDLED_CHARGES = "unbundled_charges"
    REJECTION_INVALID = "rejection_invalid"
    REJECTION_DELAYED = "rejection_delayed"
    POLICY_VIOLATION = "policy_violation"
    MISSING_ITEMIZATION = "missing_itemization"


class Confidence(Enum):
    """Confidence levels for flagged issues."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class BillingIssue:
    """Represents a single flagged issue in the bill."""
    issue_id: str
    issue_type: IssueType
    description: str
    billed_amount: float
    benchmark_amount: float | None
    overcharge_amount: float | None
    confidence: Confidence
    evidence: List[str]
    action_required: str
    benchmark_type: str = "CGHS"
    match_quality: float = 0.0
    matched_procedure: str | None = None

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return {
            **asdict(self),
            "issue_type": self.issue_type.value,
            "confidence": self.confidence.value,
        }


@dataclass
class AnalysisResult:
    """Complete bill analysis result."""
    total_bill: float
    total_approved: float
    total_rejected: float
    total_patient_liability: float
    total_verified_overcharge: float
    estimated_recoverable: Dict[str, float]
    issues: List[BillingIssue]
    summary: str
    recommendations: List[str]

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return {
            **asdict(self),
            "issues": [issue.to_dict() for issue in self.issues],
        }


class BillShieldAgent:
    """
    Main agent orchestrator for bill analysis.
    Implements SPAOR pattern: Search, Plan, Act, Observe, Reflect.
    """

    def __init__(self, rag_system=None):
        """
        Initialize agent with RAG system.

        Args:
            rag_system: BillShieldRAG instance
        """
        self.rag = rag_system
        self.issue_counter = 0

    def analyze(
        self,
        bill_data: Dict,
        discharge_data: Dict | None = None,
        rejection_data: Dict | None = None,
        policy_available: bool = False,
    ) -> AnalysisResult:
        """Main entry point: analyze uploaded documents and generate report."""
        print(f"\n{'=' * 70}")
        print("BillShield Agent Starting Analysis")
        print(f"{'=' * 70}\n")

        issues = []

        print("📋 Analyzing bill line items...")
        primary_issues, unmatched_items = self._analyze_bill_line_items(bill_data)
        issues.extend(primary_issues)

        if unmatched_items:
            print(f"\n🔧 Found {len(unmatched_items)} unmatched items, calling Universal Agent...")
            try:
                from src.agent.universal_agent import UniversalAgent

                universal_agent = UniversalAgent(rag_system=self.rag)

                universal_issues = universal_agent.analyze_unmatched_items(
                    unmatched_items=unmatched_items,
                    bill_data=bill_data,
                )

                for univ_issue in universal_issues:
                    self.issue_counter += 1

                    try:
                        issue_type_value = univ_issue.get(
                            "issue_type",
                            "procedure_overcharge",
                        )
                        confidence_value = univ_issue.get(
                            "confidence",
                            "medium",
                        )

                        issues.append(
                            BillingIssue(
                                issue_id=univ_issue["issue_id"],
                                issue_type=IssueType(issue_type_value),
                                description=univ_issue["description"],
                                billed_amount=univ_issue["billed_amount"],
                                benchmark_amount=univ_issue.get("benchmark_amount"),
                                overcharge_amount=univ_issue.get("overcharge_amount"),
                                confidence=Confidence(confidence_value),
                                evidence=univ_issue["evidence"],
                                action_required=univ_issue["action_required"],
                            )
                        )

                    except Exception as e:
                        print(f"⚠️ Failed to convert universal issue: {e}")
                        continue

            except Exception as universal_error:
                print(f"⚠️ Universal Agent failed: {universal_error}")
                import traceback
                traceback.print_exc()

        if discharge_data:
            print("📄 Cross-referencing discharge summary...")
            issues.extend(self._cross_reference_discharge(bill_data, discharge_data))

        if discharge_data:
            print("🔧 Checking multi-procedure billing discounts...")
            issues.extend(self._check_multi_procedure_billing(bill_data, discharge_data))

        if rejection_data:
            print("🔍 Analyzing insurance rejection...")
            issues.extend(self._analyze_rejection(rejection_data, bill_data))

        if policy_available:
            print("📑 Checking policy terms...")
            issues.extend(self._check_policy_compliance(bill_data, rejection_data))

        print(f"\n✅ Found {len(issues)} potential issues")
        print("🧮 Calculating totals and confidence scores...\n")

        issues = self._deduplicate_issues(issues)
        issues = self._group_surgical_packages(issues)

        result = self._generate_result(bill_data, rejection_data, issues)

        print(f"{'=' * 70}")
        print(f"Analysis Complete: {len(result.issues)} issues flagged")
        print(
            f"Estimated Recoverable: "
            f"₹{result.estimated_recoverable['min']:,.0f} - "
            f"₹{result.estimated_recoverable['max']:,.0f}"
        )
        print(f"{'=' * 70}\n")

        return result

    def _analyze_bill_line_items(self, bill_data: Dict) -> tuple[List[BillingIssue], List[Dict]]:
        """
        Analyze line items and return BOTH matched issues AND unmatched items.
        """
        issues = []
        unmatched_items = []
        line_items = bill_data.get("line_items", [])

        procedure_name = bill_data.get("procedure_name", "")
        department = bill_data.get("department", "")

        print(f"🏥 Bill Context: Procedure={procedure_name}, Department={department}")

        for item in line_items:
            description = item.get("description", "").lower()
            amount = item.get("amount", 0)
            category = item.get("category", "").lower()

            if amount == 0:
                continue

            print(f"📝 Analyzing: {description} (₹{amount})")

            issue = None

            if category == "room charges" or any(
                keyword in description
                for keyword in ["icu", "room", "bed", "ward"]
            ):
                issue = self._check_room_charges(item, bill_data)

            elif category == "nursing charges" or "nursing" in description:
                issue = self._check_cghs_overcharge(
                    item=item,
                    bill_data=bill_data,
                    issue_prefix="NURSE",
                    benchmark_label="nursing",
                    action_required="Challenge nursing charge using CGHS benchmark",
                )

            elif category == "procedure charges" or any(
                keyword in description
                for keyword in [
                    "operation",
                    "procedure",
                    "surgery",
                    "treatment",
                    "ot ",
                    "ot charges",
                    "anesthet",
                    "anaesthet",
                    "dressing",
                    "assistant",
                    "surgeon",
                ]
            ):
                issue = self._check_procedure_charges(item, bill_data)

            elif any(
                keyword in description
                for keyword in [
                    "stent",
                    "pacemaker",
                    "implant",
                    "catheter",
                    "valve",
                    "mesh",
                    "prosthesis",
                ]
            ):
                issue = self._check_device_price(item)

            elif category == "medicine" or any(
                keyword in description
                for keyword in ["medicine", "drug", "tablet", "syrup", "injection"]
            ):
                issue = self._check_drug_price(item)

            elif category == "lab tests" or any(
                keyword in description
                for keyword in [
                    "ct scan",
                    "mri",
                    "x-ray",
                    "xray",
                    "ultrasound",
                    "ecg",
                    "echo",
                    "echocardiography",
                    "lab",
                    "test",
                    "blood",
                ]
            ):
                issue = self._check_diagnostic_charges(item, bill_data)

            elif category == "doctor fees" or any(
                keyword in description
                for keyword in ["consultation", "doctor", "specialist", "visit", "consultant"]
            ):
                issue = self._check_consultation_charges(item, bill_data)

            elif category == "consumables" or any(
                keyword in description
                for keyword in ["consumable", "disposable", "gloves", "syringe"]
            ):
                issue = self._check_consumables(item)

            if issue:
                issues.append(issue)
            else:
                unmatched_items.append(item)
                print("  ⚠️ No primary match - queued for Universal Agent")

        print(f"🔍 Primary: {len(issues)} matched, {len(unmatched_items)} unmatched")
        return issues, unmatched_items

    def _match_to_benchmark(self, line_item: Dict, bill_data: Dict) -> Dict | None:
        """
        Match a line item to a CGHS benchmark using improved priority order.
        """
        if not self.rag:
            return None

        procedure_codes = line_item.get("procedure_codes") or bill_data.get("procedure_codes") or []
        if procedure_codes:
            benchmark = self._search_by_code(procedure_codes)
            if benchmark:
                print(f"✅ Matched by code: {procedure_codes}")
                return benchmark

        procedure_name = bill_data.get("procedure_name")
        if procedure_name:
            print(f"🔎 Searching CGHS for procedure: {procedure_name}")
            benchmark = self._fuzzy_search_cghs(procedure_name)
            if benchmark:
                print(f"✅ Matched by procedure name: {benchmark.get('procedure')}")
                return benchmark

        description = line_item.get("description", "")
        if procedure_name and description:
            clean_desc = description.replace(bill_data.get("department", ""), "").replace("-", "").strip()
            combined_query = f"{procedure_name} {clean_desc}"
            print(f"🔎 Searching CGHS for combined: {combined_query}")
            benchmark = self._fuzzy_search_cghs(combined_query)
            if benchmark:
                print(f"✅ Matched by combined: {benchmark.get('procedure')}")
                return benchmark

        if description:
            print(f"🔎 Searching CGHS for description: {description}")
            benchmark = self._fuzzy_search_cghs(description)
            if benchmark:
                print(f"✅ Matched by description: {benchmark.get('procedure')}")
                return benchmark

        print(f"❌ No CGHS match found for: {description}")
        return None

    def _search_by_code(self, procedure_codes: List[str]) -> Dict | None:
        """Search CGHS benchmarks using visible ICD/CPT/procedure codes."""
        if not self.rag:
            return None

        for code in procedure_codes:
            if not code:
                continue

            results = self.rag.search_cghs_rates(str(code), n_results=3)
            valid_results = [result for result in results if result.get("rate", 0) > 0]

            if valid_results:
                best_match = valid_results[0]
                best_match["match_strategy"] = "procedure_code"
                best_match["matched_query"] = str(code)
                return best_match

        return None

    def _fuzzy_search_cghs(self, query: str) -> Dict | None:
        """Search CGHS benchmarks with similarity score."""
        if not self.rag or not query:
            return None

        results = self.rag.search_cghs_rates(query, n_results=3)
        valid_results = [result for result in results if result.get("rate", 0) > 0]

        if not valid_results:
            return None

        best_match = valid_results[0]
        best_match["match_strategy"] = "fuzzy_search"
        best_match["matched_query"] = query
        return best_match

    def _web_search_cghs_rate(self, query: str) -> Dict | None:
        """
        Placeholder for future web search fallback.

        Kept intentionally non-invasive: the agent currently should not invent
        benchmarks. If no RAG benchmark exists, return None for manual review.
        """
        return None

    def _check_cghs_overcharge(
        self,
        item: Dict,
        bill_data: Dict,
        issue_prefix: str,
        benchmark_label: str,
        action_required: str,
    ) -> BillingIssue | None:
        """
        Confidence-weighted CGHS benchmark checker.

        HIGH (similarity >= 0.75): Clear match, claim overcharge with strong wording.
        MEDIUM (similarity 0.55-0.75): Possible match, request verification.
        LOW (similarity < 0.55): Different test/procedure, request itemization only.
        """
        if not self.rag:
            return None

        description = item.get("description", "")
        amount = item.get("amount", 0)

        benchmark = self._match_to_benchmark(item, bill_data)
        if not benchmark:
            # No benchmark found at all - still flag as needing itemization
            self.issue_counter += 1
            return BillingIssue(
                issue_id=f"REVIEW_{self.issue_counter:03d}",
                issue_type=IssueType.MISSING_ITEMIZATION,
                description=f"{description} — needs procedure identification",
                billed_amount=amount,
                benchmark_amount=None,
                overcharge_amount=None,
                confidence=Confidence.LOW,
                evidence=[
                    f"Billed amount: ₹{amount:,.2f}",
                    "No reliable benchmark match found for this charge",
                    "Cannot verify pricing without exact procedure name and code",
                ],
                action_required=(
                    "Request itemization and procedure code from hospital. "
                    "Ask: what exact procedure was performed and what is its tariff entry?"
                ),
                benchmark_type="CGHS",
                match_quality=0.0,
                matched_procedure=None,
            )

        cghs_rate = benchmark.get("rate", 0)
        similarity = benchmark.get("similarity", 0)
        matched_procedure = benchmark.get("procedure", "Unknown")

        if not cghs_rate:
            return None

        # Determine confidence tier based on match quality
        if similarity >= 0.75:
            confidence = Confidence.HIGH
            amount_threshold = 1.5
        elif similarity >= 0.55:
            confidence = Confidence.MEDIUM
            amount_threshold = 2.0
        else:
            # LOW CONFIDENCE: Clean, patient-friendly evidence
            # Do NOT show confusing CGHS benchmark details
            self.issue_counter += 1
            return BillingIssue(
                issue_id=f"REVIEW_{self.issue_counter:03d}",
                issue_type=IssueType.MISSING_ITEMIZATION,
                description=f"{description} — needs procedure identification",
                billed_amount=amount,
                benchmark_amount=None,
                overcharge_amount=None,
                confidence=Confidence.LOW,
                evidence=[
                    f"Billed amount: ₹{amount:,.2f}",
                    "No reliable CGHS match found for this charge",
                    "Cannot verify pricing without exact procedure name and code from hospital",
                ],
                action_required=(
                    "Before paying, ask the hospital: "
                    "(1) What exact procedure does this charge cover? "
                    "(2) What is the procedure code or tariff card entry? "
                    "(3) Is this a standalone charge or part of a package?"
                ),
                benchmark_type="CGHS",
                match_quality=similarity,
                matched_procedure=None,  # Intentionally hidden from LOW confidence cards
            )

        # HIGH or MEDIUM: Check if amount significantly exceeds benchmark
        if amount <= cghs_rate * amount_threshold:
            return None

        self.issue_counter += 1
        overcharge = amount - cghs_rate

        if confidence == Confidence.HIGH:
            issue_description = (
                f"{description} appears significantly above CGHS {benchmark_label} benchmark"
            )
            confidence_action = (
                "Request hospital to justify charge or revise it with reference to CGHS rate. "
                "Ask for procedure code and tariff card entry."
            )
        else:  # MEDIUM
            issue_description = (
                f"{description} may be above CGHS benchmark — verify test/procedure identity"
            )
            confidence_action = (
                "Request itemization and procedure code from hospital. "
                "Confirm exact test/procedure before challenging the charge."
            )

        return BillingIssue(
            issue_id=f"{issue_prefix}_{self.issue_counter:03d}",
            issue_type=IssueType.PROCEDURE_OVERCHARGE,
            description=issue_description,
            billed_amount=amount,
            benchmark_amount=cghs_rate,
            overcharge_amount=overcharge,
            confidence=confidence,
            evidence=[
                f"CGHS reference rate: ₹{cghs_rate:,.2f}",
                f"Billed amount: ₹{amount:,.2f}",
                f"Difference: {(amount / cghs_rate - 1) * 100:.0f}% above benchmark",
                f"Matched CGHS procedure: {matched_procedure}",
                f"Match quality: {similarity:.0%} ({confidence.value} confidence)",
                "Note: CGHS rates are government benchmarks. Private hospitals may charge above them with valid justification.",
            ],
            action_required=confidence_action,
            benchmark_type="CGHS",
            match_quality=similarity,
            matched_procedure=matched_procedure,
        )

    def _check_drug_price(self, item: Dict) -> BillingIssue | None:
        """Check drug pricing against NPPA ceiling."""
        if not self.rag:
            return None

        description = item.get("description", "")
        amount = item.get("amount", 0)

        nppa_results = self.rag.reference_collection.query(
            query_texts=[description],
            n_results=3,
            where={"type": "nppa_drug"},
        )

        if not nppa_results["metadatas"][0]:
            return None

        best_match = nppa_results["metadatas"][0][0]
        ceiling_price = best_match.get("ceiling_price", 0)

        if ceiling_price and amount > ceiling_price * 1.2:
            self.issue_counter += 1
            overcharge = amount - ceiling_price

            return BillingIssue(
                issue_id=f"DRUG_{self.issue_counter:03d}",
                issue_type=IssueType.DRUG_OVERCHARGE,
                description=f"{description} exceeds NPPA ceiling price",
                billed_amount=amount,
                benchmark_amount=ceiling_price,
                overcharge_amount=overcharge,
                confidence=Confidence.HIGH,
                evidence=[
                    f"NPPA ceiling price: ₹{ceiling_price:,.2f}",
                    f"Billed amount: ₹{amount:,.2f}",
                    f"Drug match: {best_match.get('drug_name', 'Unknown')}",
                ],
                action_required="Challenge drug pricing using NPPA ceiling price",
                benchmark_type="NPPA",
                match_quality=1.0,
                matched_procedure=best_match.get("drug_name", "Unknown"),
            )

        return None

    def _check_device_price(self, item: Dict) -> BillingIssue | None:
        """Check medical device pricing against NPPA ceiling."""
        if not self.rag:
            return None

        description = item.get("description", "")
        amount = item.get("amount", 0)

        if any(
            word in description.lower()
            for word in ["stent", "drug-eluting", "drug eluting", "des"]
        ):
            device_results = self.rag.reference_collection.query(
                query_texts=["drug eluting stent coronary stent DES"],
                n_results=10,
                where={"type": "nppa_device"},
            )

            candidates = []
            for doc, metadata, distance in zip(
                device_results["documents"][0],
                device_results["metadatas"][0],
                device_results["distances"][0],
            ):
                combined = f"{doc} {metadata}".lower()
                if "stent" in combined and (
                    "drug" in combined or "eluting" in combined or "des" in combined
                ):
                    candidates.append((metadata, distance))

            if candidates:
                best_match = candidates[0][0]
                ceiling_price = best_match.get("ceiling_price", 0)

                if ceiling_price and amount > ceiling_price * 1.05:
                    self.issue_counter += 1
                    overcharge = amount - ceiling_price

                    return BillingIssue(
                        issue_id=f"DEVICE_{self.issue_counter:03d}",
                        issue_type=IssueType.DEVICE_OVERCHARGE,
                        description=f"{description} exceeds NPPA ceiling price for drug-eluting stent",
                        billed_amount=amount,
                        benchmark_amount=ceiling_price,
                        overcharge_amount=overcharge,
                        confidence=Confidence.HIGH,
                        evidence=[
                            f"NPPA ceiling: ₹{ceiling_price:,.2f}",
                            f"Billed amount: ₹{amount:,.2f}",
                            f"Overcharge: ₹{overcharge:,.2f}",
                            "Matched as drug-eluting coronary stent device",
                        ],
                        action_required="Challenge stent pricing using NPPA device ceiling and request manufacturer invoice",
                        benchmark_type="NPPA",
                        match_quality=1.0,
                        matched_procedure="Drug-eluting coronary stent",
                    )

        try:
            device_results = self.rag.reference_collection.query(
                query_texts=[description],
                n_results=3,
                where={"type": "nppa_device"},
            )
        except Exception:
            return None

        if not device_results["documents"][0]:
            cghs_results = self.rag.search_cghs_rates(description, n_results=3)
            valid_results = [result for result in cghs_results if result.get("rate", 0) > 0]

            if valid_results:
                cghs_rate = valid_results[0]["rate"]
                if amount > cghs_rate * 2:
                    self.issue_counter += 1
                    overcharge = amount - cghs_rate

                    return BillingIssue(
                        issue_id=f"DEVICE_{self.issue_counter:03d}",
                        issue_type=IssueType.DEVICE_OVERCHARGE,
                        description=f"{description} exceeds CGHS benchmark (NPPA device data unavailable)",
                        billed_amount=amount,
                        benchmark_amount=cghs_rate,
                        overcharge_amount=overcharge,
                        confidence=Confidence.MEDIUM,
                        evidence=[
                            f"CGHS benchmark: ₹{cghs_rate:,.2f}",
                            f"Billed amount: ₹{amount:,.2f}",
                            "NPPA device ceiling not found; using CGHS as reference",
                        ],
                        action_required="Request itemized device bill with manufacturer invoice",
                        benchmark_type="CGHS",
                        match_quality=valid_results[0].get("similarity", 0),
                        matched_procedure=valid_results[0].get("procedure", "Unknown"),
                    )

            return None

        best_match = device_results["metadatas"][0][0]
        ceiling_price = best_match.get("ceiling_price", 0)
        similarity = 1 - device_results["distances"][0][0]

        if similarity < 0.5 or ceiling_price == 0:
            return None

        if amount > ceiling_price * 1.05:
            self.issue_counter += 1
            overcharge = amount - ceiling_price

            return BillingIssue(
                issue_id=f"DEVICE_{self.issue_counter:03d}",
                issue_type=IssueType.DEVICE_OVERCHARGE,
                description=f"{description} exceeds NPPA ceiling price",
                billed_amount=amount,
                benchmark_amount=ceiling_price,
                overcharge_amount=overcharge,
                confidence=Confidence.HIGH,
                evidence=[
                    f"NPPA ceiling: ₹{ceiling_price:,.2f}",
                    f"Billed amount: ₹{amount:,.2f}",
                    f"Overcharge: ₹{overcharge:,.2f}",
                ],
                action_required="Challenge device pricing using NPPA ceiling price",
                benchmark_type="NPPA",
                match_quality=similarity,
                matched_procedure=best_match.get("device_name", "Unknown"),
            )

        return None

    def _check_room_charges(self, item: Dict, bill_data: Dict) -> BillingIssue | None:
        """Check room/ICU charges against CGHS rates."""
        return self._check_cghs_overcharge(
            item=item,
            bill_data=bill_data,
            issue_prefix="ROOM",
            benchmark_label="room/ICU",
            action_required="Request hospital's rate card justification for room/ICU markup",
        )

    def _check_diagnostic_charges(self, item: Dict, bill_data: Dict) -> BillingIssue | None:
        """Check diagnostic test charges against CGHS rates."""
        return self._check_cghs_overcharge(
            item=item,
            bill_data=bill_data,
            issue_prefix="DIAG",
            benchmark_label="diagnostic",
            action_required="Challenge diagnostic charge using CGHS benchmark",
        )

    def _check_consultation_charges(self, item: Dict, bill_data: Dict) -> BillingIssue | None:
        """Check consultation charges against CGHS rates."""
        return self._check_cghs_overcharge(
            item=item,
            bill_data=bill_data,
            issue_prefix="CONSULT",
            benchmark_label="consultation",
            action_required="Challenge consultation charge using CGHS benchmark",
        )

    def _check_procedure_charges(self, item: Dict, bill_data: Dict) -> BillingIssue | None:
        """Check operation/procedure/surgery charges against CGHS rates."""
        return self._check_cghs_overcharge(
            item=item,
            bill_data=bill_data,
            issue_prefix="PROC",
            benchmark_label="procedure",
            action_required="Challenge procedure charge using CGHS benchmark",
        )

    def _check_consumables(self, item: Dict) -> BillingIssue | None:
        """Flag aggregated consumables without itemization."""
        description = item.get("description", "")
        amount = item.get("amount", 0)

        if amount > 10000 and "consumable" in description.lower():
            self.issue_counter += 1

            return BillingIssue(
                issue_id=f"CONS_{self.issue_counter:03d}",
                issue_type=IssueType.MISSING_ITEMIZATION,
                description="High-value consumables billed without itemization",
                billed_amount=amount,
                benchmark_amount=None,
                overcharge_amount=None,
                confidence=Confidence.MEDIUM,
                evidence=[
                    f"Aggregated charge: ₹{amount:,.2f}",
                    "No itemized breakdown provided",
                    "Per Consumer Protection Act, itemization is mandatory for charges > ₹5,000",
                ],
                action_required="Request itemized consumables list with quantities and rates",
                benchmark_type="ITEMIZATION",
                match_quality=0.0,
                matched_procedure=None,
            )

        return None

    def _cross_reference_discharge(self, bill_data: Dict, discharge_data: Dict) -> List[BillingIssue]:
        """Cross-reference bill against discharge summary for discrepancies."""
        issues = []

        consultation_items = [
            item for item in bill_data.get("line_items", [])
            if "consult" in item.get("description", "").lower()
        ]

        billed_consultations = len(consultation_items)
        discharge_procedures = len(discharge_data.get("procedures", []))

        if billed_consultations > discharge_procedures + 1:
            self.issue_counter += 1

            total_consult_charges = sum(item.get("amount", 0) for item in consultation_items)
            excess_consultations = billed_consultations - discharge_procedures
            estimated_overcharge = total_consult_charges * (
                excess_consultations / billed_consultations
            )

            issues.append(
                BillingIssue(
                    issue_id=f"DISC_{self.issue_counter:03d}",
                    issue_type=IssueType.DUPLICATE_BILLING,
                    description=(
                        f"Bill lists {billed_consultations} consultations but discharge "
                        f"summary documents {discharge_procedures} procedures"
                    ),
                    billed_amount=total_consult_charges,
                    benchmark_amount=total_consult_charges - estimated_overcharge,
                    overcharge_amount=estimated_overcharge,
                    confidence=Confidence.MEDIUM,
                    evidence=[
                        f"Consultations billed: {billed_consultations}",
                        f"Procedures in discharge: {discharge_procedures}",
                        f"Potential duplicate/phantom consultations: {excess_consultations}",
                        "Discharge summary is the authoritative record of care provided",
                    ],
                    action_required="Request detailed consultation log with doctor names, dates, and times",
                    benchmark_type="DISCHARGE_CROSS_CHECK",
                    match_quality=0.0,
                    matched_procedure=None,
                )
            )

        return issues

    def _check_multi_procedure_billing(
        self,
        bill_data: Dict,
        discharge_data: Dict,
    ) -> List[BillingIssue]:
        """
        Check if multiple procedures were billed at 100%.
        """
        raw_issues = detect_multi_procedure_violations(bill_data, discharge_data)

        issues = []
        for raw in raw_issues:
            issues.append(
                BillingIssue(
                    issue_id=raw["issue_id"],
                    issue_type=IssueType.UNBUNDLED_CHARGES,
                    description=raw["description"],
                    billed_amount=raw["billed_amount"],
                    benchmark_amount=raw["benchmark_amount"],
                    overcharge_amount=raw["overcharge_amount"],
                    confidence=Confidence.HIGH,
                    evidence=raw["evidence"],
                    action_required=raw["action_required"],
                    benchmark_type="IRDAI_MULTI_PROCEDURE",
                    match_quality=1.0,
                    matched_procedure="Multi-procedure billing rule",
                )
            )

        return issues

    def _analyze_rejection(self, rejection_data: Dict, bill_data: Dict) -> List[BillingIssue]:
        """Analyze insurance rejection for IRDAI compliance."""
        issues = []

        timeline = rejection_data.get("timeline", {})
        rejection_days = timeline.get("discharge_to_rejection_days", 0)

        if rejection_days > 15:
            self.issue_counter += 1

            irdai_results = []
            if self.rag:
                irdai_results = self.rag.search_irdai_regulations(
                    "15 day claim settlement timeline",
                    n_results=2,
                    min_similarity=0.3,
                )

            financial_summary = rejection_data.get("financial_summary", {})
            rejected_amount = financial_summary.get("amount_rejected", 0)

            evidence = [
                f"Rejection received {rejection_days} days after discharge",
                "IRDAI mandates 15-day settlement timeline",
                "Delay triggers auto-approval or interest penalty",
            ]

            if irdai_results:
                evidence.append(
                    f"Citation: {irdai_results[0]['reference']}, Page {irdai_results[0]['page']}"
                )

            issues.append(
                BillingIssue(
                    issue_id=f"REJ_{self.issue_counter:03d}",
                    issue_type=IssueType.REJECTION_DELAYED,
                    description="Claim settlement exceeded IRDAI 15-day timeline",
                    billed_amount=rejected_amount,
                    benchmark_amount=None,
                    overcharge_amount=rejected_amount,
                    confidence=Confidence.HIGH,
                    evidence=evidence,
                    action_required=(
                        "File escalation citing IRDAI timeline violation and request "
                        "interest at bank rate + 2%"
                    ),
                    benchmark_type="IRDAI_TIMELINE",
                    match_quality=1.0,
                    matched_procedure="Claim settlement timeline",
                )
            )

        timeline_issues = validate_settlement_timelines(rejection_data)
        for raw in timeline_issues:
            self.issue_counter += 1
            issues.append(
                BillingIssue(
                    issue_id=raw.get("issue_id", f"REJ_{self.issue_counter:03d}"),
                    issue_type=IssueType.REJECTION_DELAYED,
                    description=raw["description"],
                    billed_amount=raw.get("billed_amount", 0),
                    benchmark_amount=raw.get("benchmark_amount", 0),
                    overcharge_amount=raw.get("overcharge_amount", 0),
                    confidence=Confidence.MEDIUM,
                    evidence=raw["evidence"],
                    action_required=raw["action_required"],
                    benchmark_type="IRDAI_TIMELINE",
                    match_quality=0.0,
                    matched_procedure="Timeline validation",
                )
            )

        return issues

    def _check_policy_compliance(
        self,
        bill_data: Dict,
        rejection_data: Dict | None,
    ) -> List[BillingIssue]:
        """
        Check rejected items against user's policy terms and IRDAI regulations.
        """
        issues = []

        if not rejection_data or not self.rag:
            return issues

        rejection_reasons = rejection_data.get("rejection_reasons", [])

        for reason_obj in rejection_reasons:
            reason_text = reason_obj.get("reason", "")
            rejected_amount = reason_obj.get("amount", 0)

            if not reason_text or rejected_amount == 0:
                continue

            policy_results = self.rag.search_policy_exclusions(reason_text, n_results=2)

            irdai_results = self.rag.search_irdai_regulations(
                f"claim rejection {reason_text}",
                n_results=2,
            )

            if policy_results and irdai_results:
                policy_text = policy_results[0]["text"]
                irdai_text = irdai_results[0]["text"]

                if any(
                    keyword in irdai_text.lower()
                    for keyword in ["must be covered", "cannot exclude", "shall cover"]
                ) and any(
                    keyword in policy_text.lower()
                    for keyword in ["not covered", "excluded", "exclusion"]
                ):
                    self.issue_counter += 1

                    issues.append(
                        BillingIssue(
                            issue_id=f"POL_{self.issue_counter:03d}",
                            issue_type=IssueType.POLICY_VIOLATION,
                            description=(
                                f"Policy exclusion for '{reason_text}' may contradict "
                                f"IRDAI regulation"
                            ),
                            billed_amount=rejected_amount,
                            benchmark_amount=None,
                            overcharge_amount=rejected_amount,
                            confidence=Confidence.MEDIUM,
                            evidence=[
                                f"Policy clause: {policy_results[0].get('clause_number', 'N/A')}",
                                f"IRDAI reference: {irdai_results[0].get('reference', 'N/A')}",
                                "Potential contradiction between policy exclusion and IRDAI rule",
                            ],
                            action_required="Escalate to insurer grievance cell citing IRDAI regulation",
                            benchmark_type="IRDAI_POLICY",
                            match_quality=0.0,
                            matched_procedure=None,
                        )
                    )

            non_payable_results = self.rag.search_non_payable_items(reason_text, n_results=3)

            if non_payable_results:
                best_match = non_payable_results[0]
                similarity = best_match.get("similarity", 0)

                if similarity < 0.6:
                    self.issue_counter += 1

                    issues.append(
                        BillingIssue(
                            issue_id=f"REJ_{self.issue_counter:03d}",
                            issue_type=IssueType.REJECTION_INVALID,
                            description=(
                                f"Rejected item '{reason_text}' not found in IRDAI "
                                f"non-payable list"
                            ),
                            billed_amount=rejected_amount,
                            benchmark_amount=None,
                            overcharge_amount=rejected_amount,
                            confidence=Confidence.MEDIUM,
                            evidence=[
                                f"Rejection reason: {reason_text}",
                                "Item not in IRDAI's official non-payable list",
                                (
                                    f"Closest match: {best_match.get('item', 'N/A')} "
                                    f"(similarity: {similarity:.2f})"
                                ),
                            ],
                            action_required=(
                                "Challenge rejection citing IRDAI non-payable list as authority"
                            ),
                            benchmark_type="IRDAI_NON_PAYABLE",
                            match_quality=similarity,
                            matched_procedure=best_match.get("item", "N/A"),
                        )
                    )

        return issues

    def _deduplicate_issues(self, issues: List[BillingIssue]) -> List[BillingIssue]:
        """
        Remove duplicate issues that flag the same charge.
        Keeps the issue with highest confidence and largest overcharge.
        """
        import re

        def normalize_description(desc: str) -> str:
            """Normalize description for comparison."""
            normalized = desc.lower()
            prefixes = [
                "obs & gynecology - ",
                "obs & gyne - ",
                "obs & gayne - ",
                "cardiology - ",
                "orthopedics - ",
                "general surgery - ",
                "deluxe ward - ",
                "icu - ",
                "general ward - ",
            ]

            for prefix in prefixes:
                if normalized.startswith(prefix):
                    normalized = normalized[len(prefix):]
                    break

            normalized = re.sub(r"[^\w\s]", "", normalized)
            normalized = re.sub(r"\s+", " ", normalized).strip()
            return normalized

        groups = {}
        for issue in issues:
            key = (
                normalize_description(issue.description),
                round(issue.billed_amount, 2),
            )
            if key not in groups:
                groups[key] = []
            groups[key].append(issue)

        confidence_rank = {
            Confidence.HIGH: 3,
            Confidence.MEDIUM: 2,
            Confidence.LOW: 1,
        }

        deduplicated = []
        for key, group in groups.items():
            if len(group) == 1:
                deduplicated.append(group[0])
            else:
                best = max(
                    group,
                    key=lambda issue: (
                        confidence_rank.get(issue.confidence, 0),
                        issue.overcharge_amount or 0,
                    ),
                )
                print(
                    f"🔧 Deduplicated {len(group)} issues for "
                    f"'{key[0]}' → kept {best.issue_id}"
                )
                deduplicated.append(best)

        print(f"📊 Deduplication: {len(issues)} → {len(deduplicated)} issues")
        return deduplicated

    def _group_surgical_packages(self, issues: List[BillingIssue]) -> List[BillingIssue]:
        """
        Group related LOW-confidence surgical charges into package cards.
        Reduces 5 separate OT/anesthesia/assistant cards into 1 "surgical package" card.
        """
        # Separate LOW confidence surgery-related issues from others
        surgery_keywords = ['operation', 'ot ', 'anesthetic', 'anaesthetic', 'assistant', 'dressing']
        
        low_surgery = []
        other_issues = []
        
        for issue in issues:
            if issue.confidence == Confidence.LOW:
                desc_lower = issue.description.lower()
                if any(kw in desc_lower for kw in surgery_keywords):
                    low_surgery.append(issue)
                else:
                    other_issues.append(issue)
            else:
                other_issues.append(issue)
        
        # If we have multiple LOW-confidence surgery charges, group them
        if len(low_surgery) >= 3:
            total_amount = sum(i.billed_amount for i in low_surgery)
            descriptions = [i.description.split(' — ')[0] for i in low_surgery]  # Remove " — needs procedure identification"
            
            grouped = BillingIssue(
                issue_id="PKG_001",
                issue_type=IssueType.MISSING_ITEMIZATION,
                description="Surgery package charges need procedure identification",
                billed_amount=total_amount,
                benchmark_amount=None,
                overcharge_amount=None,
                confidence=Confidence.LOW,
                evidence=[
                    f"Total surgery-related charges: ₹{total_amount:,.2f}",
                    "Components: " + ", ".join(descriptions),
                    "This appears to be a surgical package but the exact procedure is not specified on the bill",
                    "Without the procedure name, we cannot verify against CGHS surgical packages",
                ],
                action_required=(
                    "Before paying, ask the hospital: (1) What exact surgical procedure was performed? "
                    "(2) What is the package code and tariff rate? "
                    "(3) Are anesthesia, OT, and assistant fees included in the package or separate?"
                ),
                benchmark_type="CGHS",
                match_quality=0.0,
                matched_procedure=None,
            )
            
            print(f"📦 Grouped {len(low_surgery)} LOW-confidence surgery charges into 1 package card")
            return other_issues + [grouped]
        
        return issues

    def _generate_result(
        self,
        bill_data: Dict,
        rejection_data: Dict | None,
        issues: List[BillingIssue],
    ) -> AnalysisResult:
        """Generate final analysis result with summary and recommendations."""
        totals = bill_data.get("totals", {})

        total_bill = (
            totals.get("extracted_grand_total")
            or bill_data.get("total_amount")
            or bill_data.get("grand_total")
            or 0
        )

        if rejection_data:
            fin_summary = rejection_data.get("financial_summary", {})
            total_approved = fin_summary.get("amount_settled", 0)
            total_rejected = fin_summary.get("amount_rejected", 0)
        else:
            total_approved = 0
            total_rejected = 0

        total_patient_liability = total_bill - total_approved

        verified_overcharge = sum(
            issue.overcharge_amount for issue in issues
            if issue.confidence == Confidence.HIGH and issue.overcharge_amount
        )

        high_conf_total = sum(
            issue.overcharge_amount or 0
            for issue in issues
            if issue.confidence == Confidence.HIGH
        )

        medium_conf_total = sum(
            issue.overcharge_amount or 0
            for issue in issues
            if issue.confidence == Confidence.MEDIUM
        )

        estimated_recoverable = {
            "min": high_conf_total,
            "max": high_conf_total + medium_conf_total * 0.6,
        }

        high_issues = [issue for issue in issues if issue.confidence == Confidence.HIGH]

        summary = f"Found {len(issues)} potential issues ({len(high_issues)} high confidence). "
        summary += f"Verified overcharges total ₹{verified_overcharge:,.0f}. "
        summary += (
            f"Estimated recoverable: ₹{estimated_recoverable['min']:,.0f} "
            f"to ₹{estimated_recoverable['max']:,.0f}."
        )

        recommendations = [
            (
                f"Present evidence for {len(high_issues)} high-confidence overcharges "
                f"(total ₹{high_conf_total:,.0f})"
            ),
            "Request itemized breakdown for all aggregated charges",
            "Cite CGHS/NPPA benchmarks when challenging specific line items",
        ]

        timeline = rejection_data.get("timeline", {}) if rejection_data else {}
        if timeline.get("discharge_to_rejection_days", 0) > 15:
            recommendations.append(
                "File IRDAI escalation for delayed settlement (auto-approval rule)"
            )

        return AnalysisResult(
            total_bill=total_bill,
            total_approved=total_approved,
            total_rejected=total_rejected,
            total_patient_liability=total_patient_liability,
            total_verified_overcharge=verified_overcharge,
            estimated_recoverable=estimated_recoverable,
            issues=issues,
            summary=summary,
            recommendations=recommendations,
        )


if __name__ == "__main__":
    print("BillShield Agent Core - Ready for integration")
    print("Import with: from src.agent.core import BillShieldAgent")