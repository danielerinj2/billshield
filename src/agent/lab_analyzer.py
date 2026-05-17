"""
Universal Lab Analyzer for BillShield.

Architecture (Proven approach):
    Bill line item: "Bact/Alert Blood Culture 1"
        ↓
    [Abbreviation Expander] - Adds: "blood culture bacterial aerobic"
        ↓
    [CGHS RAG Search] - Matches: "Bacterial culture and sensitivity - Aerobic"
        ↓
    [Confidence-Weighted Comparison]
        ↓
    BillingIssue (HIGH/MEDIUM/LOW confidence)
"""

from typing import Dict, List, Optional

from src.agent.core import (
    BillingIssue,
    AnalysisResult,
    IssueType,
    Confidence,
    sanitize_metadata_field,
)
from src.agent.abbreviation_expander import (
    expand_medical_term,
    expand_with_metadata,
    is_consumable,
)


# ============================================================================
# CONFIGURATION
# ============================================================================

HIGH_CONFIDENCE_SIMILARITY = 0.65
MEDIUM_CONFIDENCE_SIMILARITY = 0.55
LOW_CONFIDENCE_SIMILARITY = 0.45

HIGH_CONFIDENCE_OVERCHARGE_MULTIPLIER = 1.5
MEDIUM_CONFIDENCE_OVERCHARGE_MULTIPLIER = 2.0
SUSPICIOUS_OVERCHARGE_MULTIPLIER = 5.0


class LabAnalyzer:
    """Universal lab bill analyzer using abbreviation expansion + CGHS RAG."""
    
    def __init__(self, rag_system=None):
        self.rag = rag_system
        self.issue_counter = 0
    
    def analyze(self, bill_data: Dict) -> AnalysisResult:
        """Main entry point: analyze a lab bill."""
        print("=" * 70)
        print("Universal Lab Analyzer (Abbreviation Expansion + CGHS)")
        print("=" * 70)
        
        line_items = bill_data.get("line_items", [])
        total_bill = bill_data.get("total_amount") or sum(
            (item.get("amount") or 0) for item in line_items
        )
        
        print(f"🔬 Analyzing {len(line_items)} lab items")
        print(f"💰 Total bill: ₹{total_bill:,.2f}")
        
        if not self.rag:
            return self._fallback_analysis(bill_data, total_bill, line_items)
        
        issues: List[BillingIssue] = []
        analyzed_count = 0
        skipped_count = 0
        consumable_count = 0
        
        for item in line_items:
            description = item.get("description", "").strip()
            amount = item.get("amount")
            
            if not description or amount is None or amount <= 0:
                skipped_count += 1
                continue
            
            try:
                amount = float(amount)
            except (TypeError, ValueError):
                skipped_count += 1
                continue
            
            if is_consumable(description):
                print(f"  🔧 Consumable: {description} (₹{amount:,.2f})")
                consumable_count += 1
                continue
            
            analyzed_count += 1
            issue = self._analyze_lab_item(item)
            if issue:
                issues.append(issue)
        
        print(f"\n📊 Summary:")
        print(f"   Analyzed: {analyzed_count} tests")
        print(f"   Consumables: {consumable_count}")
        print(f"   Skipped: {skipped_count}")
        print(f"   Issues found: {len(issues)}")
        
        return self._build_result(bill_data, total_bill, issues, line_items)
    
    def _analyze_lab_item(self, item: Dict) -> Optional[BillingIssue]:
        """Analyze a single lab line item."""
        description = item.get("description", "")
        amount = float(item.get("amount", 0))
        
        expansion = expand_with_metadata(description)
        expanded_query = expansion["expanded"]
        
        print(f"\n  🔬 {description} (₹{amount:,.2f})")
        if expansion["expansion_count"] > 0:
            print(f"     ↳ Expanded with: {expansion['matched_abbreviations']}")
        
        cghs_match = self._find_cghs_rate(expanded_query, description)
        
        if not cghs_match:
            return self._create_no_benchmark_issue(item)
        
        cghs_rate = cghs_match['rate']
        cghs_similarity = cghs_match['similarity']
        cghs_procedure = cghs_match['procedure']
        
        print(f"     ↳ CGHS: {cghs_procedure[:50]}")
        print(f"     ↳ Rate: ₹{cghs_rate:,.2f} (sim: {cghs_similarity:.2f})")
        
        if amount <= cghs_rate * HIGH_CONFIDENCE_OVERCHARGE_MULTIPLIER:
            print(f"     ✅ Within acceptable range")
            return None
        
        if cghs_similarity >= HIGH_CONFIDENCE_SIMILARITY:
            confidence = Confidence.HIGH
        elif cghs_similarity >= MEDIUM_CONFIDENCE_SIMILARITY:
            confidence = Confidence.MEDIUM
        else:
            confidence = Confidence.LOW
        
        overcharge_multiplier = amount / cghs_rate
        if overcharge_multiplier > SUSPICIOUS_OVERCHARGE_MULTIPLIER:
            if confidence == Confidence.HIGH:
                confidence = Confidence.MEDIUM
            print(f"     ⚠️ Suspicious overcharge ({overcharge_multiplier:.1f}x) - downgrading")
        
        return self._create_overcharge_issue(item, expansion, cghs_match, confidence)
    
    def _find_cghs_rate(self, expanded_query: str, original_desc: str) -> Optional[Dict]:
        """Find CGHS rate using expanded query, fall back to original."""
        if not self.rag:
            return None
        
        best_match = None
        best_similarity = 0.0
        
        try:
            results = self.rag.search_cghs_rates(expanded_query, n_results=3)
            for result in results:
                rate = result.get('rate', 0)
                similarity = result.get('similarity', 0)
                if rate <= 0:
                    continue
                if similarity > best_similarity:
                    best_match = result
                    best_similarity = similarity
        except Exception as e:
            print(f"     ⚠️ CGHS search failed: {e}")
        
        try:
            results = self.rag.search_cghs_rates(original_desc, n_results=3)
            for result in results:
                rate = result.get('rate', 0)
                similarity = result.get('similarity', 0)
                if rate <= 0:
                    continue
                if similarity > best_similarity:
                    best_match = result
                    best_similarity = similarity
        except Exception:
            pass
        
        if best_match and best_similarity >= LOW_CONFIDENCE_SIMILARITY:
            return best_match
        
        return None
    
    def _create_overcharge_issue(
        self, item: Dict, expansion: Dict, cghs_match: Dict, confidence: Confidence,
    ) -> BillingIssue:
        """Create a billing issue for an overcharge."""
        self.issue_counter += 1
        description = item.get("description", "")
        amount = float(item.get("amount", 0))
        cghs_rate = cghs_match['rate']
        cghs_procedure = cghs_match['procedure']
        cghs_similarity = cghs_match['similarity']
        overcharge = amount - cghs_rate
        overcharge_pct = (amount / cghs_rate - 1) * 100
        
        evidence = [
            f"Billed amount: ₹{amount:,.2f}",
            f"CGHS benchmark: ₹{cghs_rate:,.2f}",
            f"Overcharge: ₹{overcharge:,.2f} ({overcharge_pct:.0f}% above CGHS)",
            f"Matched CGHS entry: {cghs_procedure}",
            f"Match quality: {cghs_similarity:.0%} ({confidence.value} confidence)",
        ]
        
        if expansion["expansion_count"] > 0:
            evidence.append(
                f"Test identified via abbreviation expansion: {', '.join(expansion['matched_abbreviations'])}"
            )
        
        if confidence != Confidence.HIGH:
            evidence.append("⚠️ Confidence reduced - verify before disputing.")
        
        if confidence == Confidence.HIGH:
            action = (
                f"Request hospital to justify ₹{amount:,.2f} for this test. "
                f"CGHS benchmark is ₹{cghs_rate:,.2f}. "
                f"Cite CGHS entry: {cghs_procedure}"
            )
        else:
            action = (
                "Verify this is the same test as the CGHS entry. "
                f"Compare with CGHS benchmark of ₹{cghs_rate:,.2f}."
            )
        
        return BillingIssue(
            issue_id=f"LAB_{self.issue_counter:03d}",
            issue_type=IssueType.PROCEDURE_OVERCHARGE,
            description=f"{description} — {overcharge_pct:.0f}% above CGHS benchmark",
            billed_amount=amount,
            benchmark_amount=cghs_rate,
            overcharge_amount=overcharge,
            confidence=confidence,
            evidence=evidence,
            action_required=action,
            benchmark_type="CGHS",
            match_quality=cghs_similarity,
            matched_procedure=cghs_procedure,
        )
    
    def _create_no_benchmark_issue(self, item: Dict) -> BillingIssue:
        """Create an issue when no CGHS benchmark is found."""
        self.issue_counter += 1
        description = item.get("description", "")
        amount = float(item.get("amount", 0))
        
        return BillingIssue(
            issue_id=f"LAB_REVIEW_{self.issue_counter:03d}",
            issue_type=IssueType.MISSING_ITEMIZATION,
            description=f"{description} — needs identification",
            billed_amount=amount,
            benchmark_amount=None,
            overcharge_amount=None,
            confidence=Confidence.LOW,
            evidence=[
                f"Billed amount: ₹{amount:,.2f}",
                "No reliable CGHS benchmark found",
                "May be a specialty test or non-standard naming",
            ],
            action_required=(
                "Ask the hospital: "
                "(1) What exact test does this represent? "
                "(2) What is the CGHS or hospital tariff code?"
            ),
            benchmark_type="CGHS",
            match_quality=0.0,
            matched_procedure=None,
        )
    
    def _fallback_analysis(
        self, bill_data: Dict, total_bill: float, line_items: List[Dict]
    ) -> AnalysisResult:
        """Fallback if RAG system isn't available."""
        return AnalysisResult(
            total_bill=total_bill,
            total_approved=total_bill,
            total_rejected=0.0,
            total_patient_liability=total_bill,
            total_verified_overcharge=0.0,
            total_unverified_charges=total_bill,
            estimated_recoverable={"min": 0.0, "max": 0.0},
            issues=[],
            summary=f"Analyzed {len(line_items)} lab items. RAG not available.",
            recommendations=["Confirm RAG system is initialized."],
        )
    
    def _build_result(
        self, bill_data: Dict, total_bill: float,
        issues: List[BillingIssue], line_items: List[Dict],
    ) -> AnalysisResult:
        """Build the final analysis result."""
        verified_overcharge = sum(
            (issue.overcharge_amount or 0)
            for issue in issues
            if issue.confidence == Confidence.HIGH and issue.overcharge_amount
        )
        
        unverified_charges = sum(
            issue.billed_amount
            for issue in issues
            if issue.confidence in (Confidence.LOW, Confidence.MEDIUM)
            and issue.issue_type == IssueType.MISSING_ITEMIZATION
        )
        
        medium_overcharge = sum(
            (issue.overcharge_amount or 0)
            for issue in issues
            if issue.confidence == Confidence.MEDIUM and issue.overcharge_amount
        )
        
        high_count = sum(1 for i in issues if i.confidence == Confidence.HIGH)
        med_count = sum(1 for i in issues if i.confidence == Confidence.MEDIUM)
        low_count = sum(1 for i in issues if i.confidence == Confidence.LOW)
        
        summary_parts = []
        if high_count:
            summary_parts.append(
                f"{high_count} confirmed overcharge(s) totalling ₹{verified_overcharge:,.0f}"
            )
        if med_count:
            summary_parts.append(f"{med_count} potential issue(s)")
        if low_count:
            summary_parts.append(f"{low_count} item(s) needing clarification")
        
        if summary_parts:
            summary = "Lab analysis: " + "; ".join(summary_parts) + "."
        else:
            summary = f"Analyzed {len(line_items)} lab items. No issues found."
        
        recommendations = []
        if high_count:
            recommendations.append(
                f"Challenge {high_count} overcharge(s) totalling ₹{verified_overcharge:,.0f} "
                "using CGHS citations."
            )
        if med_count:
            recommendations.append("Verify test identities before disputing medium-confidence issues.")
        if low_count:
            recommendations.append("Request itemized breakdown for unidentified tests.")
        
        if not recommendations:
            recommendations = ["No action needed."]
        
        header = bill_data.get('header', {})
        
        return AnalysisResult(
            total_bill=total_bill,
            total_approved=0.0,
            total_rejected=0.0,
            total_patient_liability=total_bill,
            total_verified_overcharge=verified_overcharge,
            total_unverified_charges=unverified_charges,
            estimated_recoverable={
                "min": verified_overcharge,
                "max": verified_overcharge + medium_overcharge * 0.6,
            },
            issues=issues,
            summary=summary,
            recommendations=recommendations,
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
        )


if __name__ == "__main__":
    print("LabAnalyzer module loaded successfully")
    print("Uses: abbreviation_expander.py + existing BillShieldRAG (CGHS)")
