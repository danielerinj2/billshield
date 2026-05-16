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

def sanitize_metadata_field(value: Any, max_length: int = 200) -> str | None:
    """
    Sanitize metadata extracted from vision LLM.
    Filters out hallucinations, placeholders, and garbage data.
    """
    if value is None:
        return None
    
    # Must be a string
    if not isinstance(value, str):
        return None
    
    cleaned = value.strip()
    
    # Empty or too short
    if len(cleaned) < 2:
        return None
    
    # Too long (likely hallucination)
    if len(cleaned) > max_length:
        return None
    
    # Common placeholder patterns the LLM might return
    placeholder_patterns = [
        'null', 'none', 'n/a', 'na', 'unknown', 'not visible',
        'not specified', 'not available', 'not provided',
        '[hospital name]', '[bill number]', '[patient name]',
        '[insert', 'tbd', 'pending', '---', '___'
    ]
    
    cleaned_lower = cleaned.lower()
    if cleaned_lower in placeholder_patterns:
        return None
    
    # Check if it's just brackets/placeholders
    if cleaned.startswith('[') and cleaned.endswith(']'):
        return None
    
    return cleaned

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
    SURGICAL_PACKAGE = "surgical_package"
    ROOM_STAY_PACKAGE = "room_stay_package"


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
    total_unverified_charges: float
    estimated_recoverable: Dict[str, float]
    issues: List[BillingIssue]
    summary: str
    recommendations: List[str]
    # Metadata fields (optional, default None for backwards compatibility)
    hospital_name: str | None = None
    bill_number: str | None = None
    bill_date: str | None = None
    patient_name: str | None = None
    patient_id: str | None = None
    admission_date: str | None = None
    discharge_date: str | None = None
    policy_number: str | None = None
    claim_number: str | None = None
    insurer_name: str | None = None

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return {
            **asdict(self),
            "issues": [issue.to_dict() for issue in self.issues],
        }


# Episode detection constants
SURGICAL_KEYWORDS = [
    "operation", "surgery", "ot ", "ot charges", "ot assistant",
    "anesthet", "anaesthet", "surgeon", "procedure charges",
    "dressing", "assistant", "operative",
]

ROOM_KEYWORDS = [
    "room", "bed", "ward", "icu", "ccu", "nicu", "picu", "hdu",
    "deluxe", "private", "general ward", "semi-private", "suite",
]

ATOMIC_KEYWORDS = [
    "blood", "cbc", "lft", "rft", "kft", "test", "lab",
    "x-ray", "xray", "mri", "ct scan", "ultrasound", "ecg", "echo",
    "consultation", "consultant", "doctor", "specialist", "visit",
    "tablet", "syrup", "injection", "medicine", "drug",
    "stent", "implant", "catheter", "valve", "mesh",
]


class BillShieldAgent:
    """
    Main agent orchestrator for bill analysis.
    Implements episode detection + atomic benchmarking.
    """

    def __init__(self, rag_system=None):
        """Initialize agent with RAG system."""
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

        # ========== PHASE 1: DOCUMENT ROUTING ==========
        # Classify document type and route to specialist analyzer
        from src.agent.document_classifier import classify_document, DocumentType

        doc_type = classify_document(bill_data)
        print(f"📋 Document classified as: {doc_type}\n")

        if doc_type == DocumentType.PHARMACY_BILL:
            print("🔀 Routing to Pharmacy Analyzer...")
            from src.agent.pharmacy_analyzer import PharmacyAnalyzer

            analyzer = PharmacyAnalyzer(rag_system=self.rag)
            return analyzer.analyze(bill_data)

        elif doc_type == DocumentType.LAB_BILL:
            print("🔀 Routing to Lab Analyzer...")
            from src.agent.lab_analyzer import LabAnalyzer

            analyzer = LabAnalyzer(rag_system=self.rag)
            return analyzer.analyze(bill_data)

        elif doc_type == DocumentType.UNKNOWN:
            print("⚠️  Document type unclear - using hospital bill analyzer as fallback\n")

        else:
            print(f"✓ Using Hospital Bill Analyzer for {doc_type}\n")

        # ========== PHASE 1 ROUTING ENDS ==========
        # For HOSPITAL_BILL and UNKNOWN, continue with existing hospital bill logic below

        issues = []

        # Detect episodes (surgical packages, room stays) first
        print("🔍 Detecting episodic charges (surgical packages, room stays)...")
        episodes, atomic_items = self._detect_episodes(bill_data)
        print(f"📦 Found {len(episodes)} episode(s), {len(atomic_items)} atomic item(s)")

        # Create one issue per episode (no benchmarking sub-charges)
        for episode in episodes:
            episode_issue = self._create_episode_issue(episode, bill_data)
            if episode_issue:
                issues.append(episode_issue)

        # Run atomic items through existing benchmark logic
        print("\n📋 Analyzing atomic line items...")
        atomic_issues, unmatched_items = self._analyze_atomic_items(atomic_items, bill_data)
        issues.extend(atomic_issues)

        # Universal agent for unmatched atomic items
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
                        issues.append(
                            BillingIssue(
                                issue_id=univ_issue["issue_id"],
                                issue_type=IssueType(
                                    univ_issue.get("issue_type", "procedure_overcharge")
                                ),
                                description=univ_issue["description"],
                                billed_amount=univ_issue["billed_amount"],
                                benchmark_amount=univ_issue.get("benchmark_amount"),
                                overcharge_amount=univ_issue.get("overcharge_amount"),
                                confidence=Confidence(univ_issue.get("confidence", "medium")),
                                evidence=univ_issue["evidence"],
                                action_required=univ_issue["action_required"],
                            )
                        )
                    except Exception as e:
                        print(f"⚠️ Failed to convert universal issue: {e}")
                        continue

            except Exception as universal_error:
                print(f"⚠️ Universal Agent failed: {universal_error}")

        if discharge_data:
            print("📄 Cross-referencing discharge summary...")
            issues.extend(self._cross_reference_discharge(bill_data, discharge_data))

            print("🔧 Checking multi-procedure billing discounts...")
            issues.extend(self._check_multi_procedure_billing(bill_data, discharge_data))

        if rejection_data:
            print("🔍 Analyzing insurance rejection...")
            issues.extend(self._analyze_rejection(rejection_data, bill_data))

        if policy_available:
            print("📑 Checking policy terms...")
            issues.extend(self._check_policy_compliance(bill_data, rejection_data))

        print(f"\n✅ Found {len(issues)} potential issues")
        issues = self._deduplicate_issues(issues)

        result = self._generate_result(bill_data, rejection_data, issues)

        print(f"{'=' * 70}")
        print(f"Analysis Complete: {len(result.issues)} issues flagged")
        print(f"Confirmed overcharges: ₹{result.total_verified_overcharge:,.0f}")
        print(f"Unverified charges: ₹{result.total_unverified_charges:,.0f}")
        print(f"{'=' * 70}\n")

        return result

    def _detect_episodes(self, bill_data: Dict) -> tuple[List[Dict], List[Dict]]:
        """
        Detect episodic charges (surgical packages, room stays) vs atomic charges.

        Returns:
            (episodes, atomic_items) where each episode is a dict with:
                - type: 'surgical' or 'room_stay'
                - department: e.g. 'OBS & GYNE'
                - items: list of line items in this episode
                - total: sum of amounts
        """
        line_items = bill_data.get("line_items", [])
        if not line_items:
            return [], []

        surgical_items = []
        room_items = []
        atomic_items = []

        for item in line_items:
            description = item.get("description", "").lower()
            category = item.get("category", "").lower()

            is_surgical = (
                category == "procedure charges"
                or any(keyword in description for keyword in SURGICAL_KEYWORDS)
            )

            is_room = (
                category == "room charges"
                or any(keyword in description for keyword in ROOM_KEYWORDS)
            )

            is_atomic = any(keyword in description for keyword in ATOMIC_KEYWORDS)

            if is_surgical:
                surgical_items.append(item)
            elif is_room:
                room_items.append(item)
            elif is_atomic:
                atomic_items.append(item)
            else:
                atomic_items.append(item)

        episodes = []

        if surgical_items:
            episodes.append(
                {
                    "type": "surgical",
                    "department": bill_data.get("department"),
                    "procedure_name": bill_data.get("procedure_name"),
                    "items": surgical_items,
                    "total": sum(item.get("amount", 0) for item in surgical_items),
                }
            )

        if room_items:
            episodes.append(
                {
                    "type": "room_stay",
                    "room_category": bill_data.get("room_category"),
                    "items": room_items,
                    "total": sum(item.get("amount", 0) for item in room_items),
                }
            )

        return episodes, atomic_items

        # Group items by department/category
        dept_groups = {}
        for item in line_items:
            desc = item.get("description", "").lower()
            category = item.get("category", "").lower()
            amount = item.get("amount", 0)

            if amount == 0:
                continue

            # Identify which group this item belongs to
            group_key = self._classify_item_for_episode(desc, category)
            if group_key not in dept_groups:
                dept_groups[group_key] = []
            dept_groups[group_key].append(item)

        episodes = []
        atomic_items = []

        for group_key, items in dept_groups.items():
            group_type, group_label = group_key

            if group_type == "surgical" and len(items) >= 2:
                # Confirm it's a surgical episode (has at least one surgical keyword)
                has_surgical_marker = any(
                    any(kw in item.get("description", "").lower() for kw in SURGICAL_KEYWORDS)
                    for item in items
                )
                if has_surgical_marker:
                    episodes.append({
                        "type": "surgical",
                        "department": group_label,
                        "items": items,
                        "total": sum(i.get("amount", 0) for i in items),
                    })
                    continue

            if group_type == "room_stay" and len(items) >= 2:
                episodes.append({
                    "type": "room_stay",
                    "department": group_label,
                    "items": items,
                    "total": sum(i.get("amount", 0) for i in items),
                })
                continue

            # Not an episode - add to atomic
            atomic_items.extend(items)

        return episodes, atomic_items

    def _classify_item_for_episode(self, description: str, category: str) -> tuple[str, str]:
        """
        Classify an item to determine if it belongs to a surgical or room-stay episode.

        Returns:
            (episode_type, department_label) tuple as a group key.
            episode_type: 'surgical', 'room_stay', or 'atomic'
        """
        desc = description.lower()

        # Atomic checks first (highest priority - these are never grouped)
        if any(kw in desc for kw in ATOMIC_KEYWORDS):
            return ("atomic", desc)

        # Surgical episode detection: looks for department prefix + surgical context
        surgical_departments = [
            "obs & gyne", "obs & gynecology", "obs & gayne", "obstetric", "gynecology",
            "cardiology", "cardiac", "orthopedic", "ortho", "neurology", "neuro",
            "general surgery", "surgery", "urology", "ent", "ophthalmology",
        ]

        for dept in surgical_departments:
            if dept in desc:
                # Check if this has surgical keywords or procedure category
                if any(kw in desc for kw in SURGICAL_KEYWORDS) or "procedure" in category:
                    return ("surgical", dept.upper())

        # Room/ward stay episode detection
        for room_kw in ROOM_KEYWORDS:
            if room_kw in desc:
                # Extract room type as label
                for room_type in ["deluxe", "private", "icu", "ccu", "nicu", "general ward", "semi-private", "suite"]:
                    if room_type in desc:
                        return ("room_stay", room_type.upper())
                return ("room_stay", "ROOM/WARD")

        # Default: atomic (will be benchmarked individually)
        return ("atomic", desc)

    def _create_episode_issue(self, episode: Dict, bill_data: Dict) -> BillingIssue | None:
        """Create a single grouped issue for a surgical or room-stay episode."""
        episode_type = episode["type"]
        department = episode.get("department", "Unknown")
        items = episode.get("items", [])
        total = episode.get("total", 0)

        self.issue_counter += 1
        bill_total = bill_data.get("total_amount", 0) or bill_data.get("grand_total", 0) or 0
        share_pct = (total / bill_total * 100) if bill_total else 0

        # Build evidence: list sub-charges
        evidence = [
            f"Total package amount: ₹{total:,.2f}",
            f"This is {share_pct:.0f}% of your total bill (₹{bill_total:,.2f})" if bill_total else "",
            "Components billed:",
        ]
        for item in items:
            desc = item.get("description", "")
            amt = item.get("amount", 0)
            evidence.append(f"  • {desc}: ₹{amt:,.2f}")

        evidence = [line for line in evidence if line]  # remove empty strings

        if episode_type == "surgical":
            procedure_name = bill_data.get("procedure_name")

            if procedure_name:
                # Procedure is known - we could benchmark, but for safety still group
                description = f"{department} surgical package - {procedure_name}"
                evidence.append(f"Procedure on file: {procedure_name}")
                evidence.append("CGHS prices surgery as a package (includes OT, anesthesia, assistant, dressings)")
                action = (
                    f"Verify with hospital: (1) Is this a fixed package rate for {procedure_name}? "
                    f"(2) What is the CGHS/hospital tariff for this procedure? "
                    f"(3) Are all sub-charges (OT, anesthesia, assistant) included in the package?"
                )
            else:
                description = f"{department} surgical package - procedure not specified on bill"
                evidence.append("⚠️ The exact procedure name is not listed on this bill")
                evidence.append("CGHS prices surgery as a single package (includes OT, anesthesia, assistant, dressings)")
                action = (
                    "Before paying, ask the hospital: "
                    "(1) What is the exact procedure name and code? "
                    "(2) Is this a fixed package, and what is the standard package rate for your room category? "
                    "(3) Are OT, anesthesia, assistant charges and dressings included in that package? "
                    "Once you have the procedure name, re-run the analysis for benchmark comparison."
                )

            return BillingIssue(
                issue_id=f"PKG_{self.issue_counter:03d}",
                issue_type=IssueType.SURGICAL_PACKAGE,
                description=description,
                billed_amount=total,
                benchmark_amount=None,
                overcharge_amount=None,
                confidence=Confidence.LOW,
                evidence=evidence,
                action_required=action,
                benchmark_type="CGHS",
                match_quality=0.0,
                matched_procedure=procedure_name,
            )

        elif episode_type == "room_stay":
            room_category = bill_data.get("room_category", department)
            description = f"{department} room/stay charges - needs tariff verification"
            evidence.append(f"Room category: {room_category}")
            evidence.append("Room charges should align with hospital's published daily tariff")

            action = (
                f"Ask the hospital: "
                f"(1) What is the standard daily tariff for {room_category}? "
                f"(2) Does this tariff include nursing, RMO, doctor visits? "
                f"(3) Is your insurance room rent limit being applied correctly?"
            )

            return BillingIssue(
                issue_id=f"ROOM_{self.issue_counter:03d}",
                issue_type=IssueType.ROOM_STAY_PACKAGE,
                description=description,
                billed_amount=total,
                benchmark_amount=None,
                overcharge_amount=None,
                confidence=Confidence.LOW,
                evidence=evidence,
                action_required=action,
                benchmark_type="HOSPITAL_TARIFF",
                match_quality=0.0,
                matched_procedure=None,
            )

        return None

    def _analyze_atomic_items(self, atomic_items: List[Dict], bill_data: Dict) -> tuple[List[BillingIssue], List[Dict]]:
        """Analyze atomic (non-episode) line items individually."""
        issues = []
        unmatched_items = []

        procedure_name = bill_data.get("procedure_name", "")
        department = bill_data.get("department", "")
        print(f"🏥 Bill Context: Procedure={procedure_name}, Department={department}")

        for item in atomic_items:
            description = item.get("description", "").lower()
            amount = item.get("amount", 0)
            category = item.get("category", "").lower()

            if amount == 0:
                continue

            print(f"📝 Analyzing: {description} (₹{amount})")
            issue = None

            # Drugs (NPPA benchmark)
            if any(kw in description for kw in ["medicine", "drug", "tablet", "syrup", "injection"]):
                issue = self._check_drug_price(item)

            # Devices (NPPA benchmark)
            elif any(kw in description for kw in ["stent", "pacemaker", "implant", "catheter", "valve", "mesh", "prosthesis"]):
                issue = self._check_device_price(item)

            # Diagnostics (CGHS benchmark - per test)
            elif any(kw in description for kw in ["ct scan", "mri", "x-ray", "xray", "ultrasound", "ecg", "echo", "lab", "test", "blood", "cbc"]):
                issue = self._check_cghs_overcharge(
                    item, bill_data, "DIAG", "diagnostic",
                    "Challenge diagnostic charge using CGHS benchmark"
                )

            # Consultations (CGHS benchmark)
            elif any(kw in description for kw in ["consultation", "consultant", "doctor", "specialist", "visit"]):
                issue = self._check_cghs_overcharge(
                    item, bill_data, "CONSULT", "consultation",
                    "Challenge consultation charge using CGHS benchmark"
                )

            # Consumables (itemization check)
            elif "consumable" in description or "disposable" in description:
                issue = self._check_consumables(item)

            if issue:
                issues.append(issue)
            else:
                unmatched_items.append(item)
                print("  ⚠️ No primary match - queued for Universal Agent")

        print(f"🔍 Atomic: {len(issues)} matched, {len(unmatched_items)} unmatched")
        return issues, unmatched_items

    def _match_to_benchmark(self, line_item: Dict, bill_data: Dict) -> Dict | None:
        """Match a line item to a CGHS benchmark."""
        if not self.rag:
            return None

        procedure_codes = line_item.get("procedure_codes") or bill_data.get("procedure_codes") or []
        if procedure_codes:
            benchmark = self._search_by_code(procedure_codes)
            if benchmark:
                print(f"✅ Matched by code: {procedure_codes}")
                return benchmark

        description = line_item.get("description", "")
        if description:
            print(f"🔎 Searching CGHS for: {description}")
            benchmark = self._fuzzy_search_cghs(description)
            if benchmark:
                print(f"✅ Matched: {benchmark.get('procedure')} (sim: {benchmark.get('similarity', 0):.2f})")
                return benchmark

        print(f"❌ No CGHS match for: {description}")
        return None

    def _search_by_code(self, procedure_codes: List[str]) -> Dict | None:
        """Search CGHS benchmarks using procedure codes."""
        if not self.rag:
            return None

        for code in procedure_codes:
            if not code:
                continue
            results = self.rag.search_cghs_rates(str(code), n_results=3)
            valid_results = [r for r in results if r.get("rate", 0) > 0]
            if valid_results:
                best = valid_results[0]
                best["match_strategy"] = "procedure_code"
                return best
        return None

    def _fuzzy_search_cghs(self, query: str) -> Dict | None:
        """Fuzzy search CGHS benchmarks."""
        if not self.rag or not query:
            return None

        results = self.rag.search_cghs_rates(query, n_results=3)
        valid_results = [r for r in results if r.get("rate", 0) > 0]
        if not valid_results:
            return None

        best = valid_results[0]
        best["match_strategy"] = "fuzzy_search"
        return best

    def _check_cghs_overcharge(
        self, item: Dict, bill_data: Dict,
        issue_prefix: str, benchmark_label: str, action_required: str,
    ) -> BillingIssue | None:
        """
        Confidence-weighted CGHS checker for ATOMIC items only.
        Surgical sub-charges should NEVER reach this function.

        HIGH (similarity >= 0.75): Clear match, claim overcharge.
        MEDIUM (similarity 0.65-0.75): Possible match, verify first.
        LOW (similarity < 0.65): Different item, request itemization.
        """
        if not self.rag:
            return None

        description = item.get("description", "")
        amount = item.get("amount", 0)

        benchmark = self._match_to_benchmark(item, bill_data)
        if not benchmark:
            self.issue_counter += 1
            return BillingIssue(
                issue_id=f"REVIEW_{self.issue_counter:03d}",
                issue_type=IssueType.MISSING_ITEMIZATION,
                description=f"{description} — needs identification",
                billed_amount=amount,
                benchmark_amount=None,
                overcharge_amount=None,
                confidence=Confidence.LOW,
                evidence=[
                    f"Billed amount: ₹{amount:,.2f}",
                    "No reliable benchmark match found",
                    "Cannot verify without exact item name or code",
                ],
                action_required="Request itemization and exact item/test name from hospital.",
                benchmark_type="CGHS",
                match_quality=0.0,
                matched_procedure=None,
            )

        cghs_rate = benchmark.get("rate", 0)
        similarity = benchmark.get("similarity", 0)
        matched_procedure = benchmark.get("procedure", "Unknown")

        if not cghs_rate:
            return None

        # Stricter thresholds for atomic items
        if similarity >= 0.75:
            confidence = Confidence.HIGH
            amount_threshold = 1.5
        elif similarity >= 0.65:
            confidence = Confidence.MEDIUM
            amount_threshold = 2.0
        else:
            # LOW confidence: clean evidence, no misleading CGHS numbers
            self.issue_counter += 1
            return BillingIssue(
                issue_id=f"REVIEW_{self.issue_counter:03d}",
                issue_type=IssueType.MISSING_ITEMIZATION,
                description=f"{description} — needs identification",
                billed_amount=amount,
                benchmark_amount=None,
                overcharge_amount=None,
                confidence=Confidence.LOW,
                evidence=[
                    f"Billed amount: ₹{amount:,.2f}",
                    "No reliable CGHS match found for this charge",
                    "Cannot verify without exact item name or test code",
                ],
                action_required=(
                    "Ask the hospital: "
                    "(1) What exact item/test does this cover? "
                    "(2) What is the CGHS or hospital tariff code? "
                    "(3) Is this billed individually or as part of a package?"
                ),
                benchmark_type="CGHS",
                match_quality=similarity,
                matched_procedure=None,
            )

        if amount <= cghs_rate * amount_threshold:
            return None

        self.issue_counter += 1
        overcharge = amount - cghs_rate

        if confidence == Confidence.HIGH:
            issue_description = f"{description} significantly above CGHS {benchmark_label} benchmark"
            confidence_action = (
                "Request hospital to justify or revise this charge using CGHS rate. "
                "Cite the matched CGHS procedure and tariff entry."
            )
        else:  # MEDIUM
            issue_description = f"{description} may be above CGHS benchmark — verify identity"
            confidence_action = (
                "Before challenging: verify this is the exact CGHS-matched test/procedure. "
                "Request item code from hospital and cross-check the benchmark."
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
                f"Matched CGHS entry: {matched_procedure}",
                f"Match quality: {similarity:.0%} ({confidence.value} confidence)",
                "Note: CGHS rates are government benchmarks. Private hospitals may charge above with valid justification.",
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

        if any(word in description.lower() for word in ["stent", "drug-eluting", "drug eluting", "des"]):
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
                if "stent" in combined and ("drug" in combined or "eluting" in combined or "des" in combined):
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
                query_texts=[description], n_results=3, where={"type": "nppa_device"},
            )
        except Exception:
            return None

        if not device_results["documents"][0]:
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
            estimated_overcharge = total_consult_charges * (excess_consultations / billed_consultations)

            issues.append(BillingIssue(
                issue_id=f"DISC_{self.issue_counter:03d}",
                issue_type=IssueType.DUPLICATE_BILLING,
                description=f"Bill lists {billed_consultations} consultations but discharge summary documents {discharge_procedures} procedures",
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
            ))
        return issues

    def _check_multi_procedure_billing(self, bill_data: Dict, discharge_data: Dict) -> List[BillingIssue]:
        """Check if multiple procedures were billed at 100%."""
        raw_issues = detect_multi_procedure_violations(bill_data, discharge_data)
        issues = []
        for raw in raw_issues:
            issues.append(BillingIssue(
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
            ))
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
                    "15 day claim settlement timeline", n_results=2, min_similarity=0.3,
                )

            financial_summary = rejection_data.get("financial_summary", {})
            rejected_amount = financial_summary.get("amount_rejected", 0)
            evidence = [
                f"Rejection received {rejection_days} days after discharge",
                "IRDAI mandates 15-day settlement timeline",
                "Delay triggers auto-approval or interest penalty",
            ]
            if irdai_results:
                evidence.append(f"Citation: {irdai_results[0]['reference']}, Page {irdai_results[0]['page']}")

            issues.append(BillingIssue(
                issue_id=f"REJ_{self.issue_counter:03d}",
                issue_type=IssueType.REJECTION_DELAYED,
                description="Claim settlement exceeded IRDAI 15-day timeline",
                billed_amount=rejected_amount,
                benchmark_amount=None,
                overcharge_amount=rejected_amount,
                confidence=Confidence.HIGH,
                evidence=evidence,
                action_required="File escalation citing IRDAI timeline violation and request interest at bank rate + 2%",
                benchmark_type="IRDAI_TIMELINE",
                match_quality=1.0,
                matched_procedure="Claim settlement timeline",
            ))

        timeline_issues = validate_settlement_timelines(rejection_data)
        for raw in timeline_issues:
            self.issue_counter += 1
            issues.append(BillingIssue(
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
            ))
        return issues

    def _check_policy_compliance(self, bill_data: Dict, rejection_data: Dict | None) -> List[BillingIssue]:
        """Check rejected items against user's policy terms and IRDAI regulations."""
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
            irdai_results = self.rag.search_irdai_regulations(f"claim rejection {reason_text}", n_results=2)

            if policy_results and irdai_results:
                policy_text = policy_results[0]["text"]
                irdai_text = irdai_results[0]["text"]
                if (any(kw in irdai_text.lower() for kw in ["must be covered", "cannot exclude", "shall cover"])
                        and any(kw in policy_text.lower() for kw in ["not covered", "excluded", "exclusion"])):
                    self.issue_counter += 1
                    issues.append(BillingIssue(
                        issue_id=f"POL_{self.issue_counter:03d}",
                        issue_type=IssueType.POLICY_VIOLATION,
                        description=f"Policy exclusion for '{reason_text}' may contradict IRDAI regulation",
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
                    ))

            non_payable_results = self.rag.search_non_payable_items(reason_text, n_results=3)
            if non_payable_results:
                best_match = non_payable_results[0]
                similarity = best_match.get("similarity", 0)
                if similarity < 0.6:
                    self.issue_counter += 1
                    issues.append(BillingIssue(
                        issue_id=f"REJ_{self.issue_counter:03d}",
                        issue_type=IssueType.REJECTION_INVALID,
                        description=f"Rejected item '{reason_text}' not found in IRDAI non-payable list",
                        billed_amount=rejected_amount,
                        benchmark_amount=None,
                        overcharge_amount=rejected_amount,
                        confidence=Confidence.MEDIUM,
                        evidence=[
                            f"Rejection reason: {reason_text}",
                            "Item not in IRDAI's official non-payable list",
                            f"Closest match: {best_match.get('item', 'N/A')} (similarity: {similarity:.2f})",
                        ],
                        action_required="Challenge rejection citing IRDAI non-payable list as authority",
                        benchmark_type="IRDAI_NON_PAYABLE",
                        match_quality=similarity,
                        matched_procedure=best_match.get("item", "N/A"),
                    ))
        return issues

    def _deduplicate_issues(self, issues: List[BillingIssue]) -> List[BillingIssue]:
        """Remove duplicate issues that flag the same charge."""
        import re

        def normalize_description(desc: str) -> str:
            normalized = desc.lower()
            prefixes = [
                "obs & gynecology - ", "obs & gyne - ", "obs & gayne - ",
                "cardiology - ", "orthopedics - ", "general surgery - ",
                "deluxe ward - ", "icu - ", "general ward - ",
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
            key = (normalize_description(issue.description), round(issue.billed_amount, 2))
            if key not in groups:
                groups[key] = []
            groups[key].append(issue)

        confidence_rank = {Confidence.HIGH: 3, Confidence.MEDIUM: 2, Confidence.LOW: 1}
        deduplicated = []
        for key, group in groups.items():
            if len(group) == 1:
                deduplicated.append(group[0])
            else:
                best = max(group, key=lambda i: (confidence_rank.get(i.confidence, 0), i.overcharge_amount or 0))
                print(f"🔧 Deduplicated {len(group)} issues for '{key[0]}' → kept {best.issue_id}")
                deduplicated.append(best)

        print(f"📊 Deduplication: {len(issues)} → {len(deduplicated)} issues")
        return deduplicated

    def _generate_result(
        self, bill_data: Dict, rejection_data: Dict | None, issues: List[BillingIssue],
    ) -> AnalysisResult:
        """Generate final analysis result with honest hero summary."""
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

        # CONFIRMED overcharges: only HIGH confidence with actual overcharge_amount
        verified_overcharge = sum(
            issue.overcharge_amount for issue in issues
            if issue.confidence == Confidence.HIGH and issue.overcharge_amount
        )

        # UNVERIFIED charges: episodes + LOW/MEDIUM confidence items that need clarification
        unverified_charges = sum(
            issue.billed_amount for issue in issues
            if issue.confidence in (Confidence.LOW, Confidence.MEDIUM)
            and issue.issue_type in (
                IssueType.SURGICAL_PACKAGE,
                IssueType.ROOM_STAY_PACKAGE,
                IssueType.MISSING_ITEMIZATION,
            )
        )

        high_conf_total = verified_overcharge
        medium_conf_total = sum(
            issue.overcharge_amount or 0
            for issue in issues
            if issue.confidence == Confidence.MEDIUM and issue.overcharge_amount
        )

        estimated_recoverable = {
            "min": high_conf_total,
            "max": high_conf_total + medium_conf_total * 0.6,
        }

        high_issues = [i for i in issues if i.confidence == Confidence.HIGH]
        episode_issues = [
            i for i in issues
            if i.issue_type in (IssueType.SURGICAL_PACKAGE, IssueType.ROOM_STAY_PACKAGE)
        ]

        # Build honest summary
        summary_parts = []
        if high_issues:
            summary_parts.append(f"{len(high_issues)} confirmed overcharge(s) totalling ₹{verified_overcharge:,.0f}")
        if episode_issues:
            summary_parts.append(f"{len(episode_issues)} package(s) needing procedure verification")

        unverified_count = sum(
            1 for i in issues
            if i.confidence == Confidence.LOW and i.issue_type == IssueType.MISSING_ITEMIZATION
        )
        if unverified_count:
            summary_parts.append(f"{unverified_count} item(s) needing clarification")

        if summary_parts:
            summary = "Found: " + "; ".join(summary_parts) + "."
        else:
            summary = "No issues detected. Bill appears compliant with available benchmarks."

        # Action plan
        recommendations = []
        if episode_issues:
            recommendations.append(
                "Before paying: identify the exact procedure name and CGHS/hospital package rate."
            )
        if high_issues:
            recommendations.append(
                f"Challenge {len(high_issues)} confirmed overcharge(s) totalling ₹{verified_overcharge:,.0f} with CGHS/NPPA citations."
            )
        if unverified_count:
            recommendations.append(
                "Request itemized breakdown for charges that could not be benchmarked."
            )

        timeline = rejection_data.get("timeline", {}) if rejection_data else {}
        if timeline.get("discharge_to_rejection_days", 0) > 15:
            recommendations.append(
                "File IRDAI escalation for delayed settlement (auto-approval rule)."
            )

        if not recommendations:
            recommendations = ["No action needed at this time."]


# Extract metadata from bill_data (handles both vision LLM and regex parser outputs)
# Vision parser puts metadata at top level; regex parser puts it under 'header'
        header = bill_data.get('header', {})
        return AnalysisResult(
            total_bill=total_bill,
            total_approved=total_approved,
            total_rejected=total_rejected,
            total_patient_liability=total_patient_liability,
            total_verified_overcharge=verified_overcharge,
            total_unverified_charges=unverified_charges,
            estimated_recoverable=estimated_recoverable,
            issues=issues,
            summary=summary,
            recommendations=recommendations,
            # Metadata - try vision LLM keys (top-level) first, then regex parser keys (header)
            hospital_name=sanitize_metadata_field(
                bill_data.get('hospital_name') or header.get('hospital_name')
            ),
            bill_number=sanitize_metadata_field(
                bill_data.get('bill_number') or header.get('bill_number')
            ),
            bill_date=sanitize_metadata_field(
                bill_data.get('bill_date') or header.get('bill_date')
            ),
            patient_name=sanitize_metadata_field(
                bill_data.get('patient_name') or header.get('patient_name')
            ),
            patient_id=sanitize_metadata_field(
                bill_data.get('patient_id') or header.get('patient_id')
            ),
            admission_date=sanitize_metadata_field(
                bill_data.get('admission_date') or header.get('admission_date')
            ),
            discharge_date=sanitize_metadata_field(
                bill_data.get('discharge_date') or header.get('discharge_date')
            ),
            policy_number=sanitize_metadata_field(
                bill_data.get('policy_number') or header.get('policy_number')
            ),
            claim_number=sanitize_metadata_field(
                bill_data.get('claim_number') or header.get('claim_number')
            ),
            insurer_name=sanitize_metadata_field(
                bill_data.get('insurer_name') or header.get('insurer_name')
            ),
        )


if __name__ == "__main__":
    print("BillShield Agent Core - Ready for integration")