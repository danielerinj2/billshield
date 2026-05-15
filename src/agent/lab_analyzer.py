"""Lab Bill Analyzer - Phase 2A"""
from typing import Dict, List
from src.agent.core import BillingIssue, AnalysisResult, IssueType, Confidence


class LabAnalyzer:
    def __init__(self, rag_system=None):
        self.rag = rag_system
        self.issue_counter = 0

    def analyze(self, bill_data: Dict) -> AnalysisResult:
        print("=" * 70)
        print("Lab Bill Analyzer")
        print("=" * 70)
        line_items = bill_data.get("line_items", [])
        print(f"🔬 Analyzing {len(line_items)} lab tests...")

        issues = []
        for item in line_items:
            issue = self._check_arithmetic(item)
            if issue:
                issues.append(issue)

        repeat_issues = self._check_repeat_tests(line_items)
        issues.extend(repeat_issues)

        total_bill = bill_data.get("total_amount") or sum(
            (item.get("amount") or 0) for item in line_items
        )
        verified_overcharge = sum(
            (i.overcharge_amount or 0) for i in issues if (i.overcharge_amount or 0) > 0
        )

        print(f"✅ Found {len(issues)} lab issues")

        return AnalysisResult(
            total_bill=total_bill,
            total_approved=total_bill,
            total_rejected=0.0,
            total_patient_liability=total_bill,
            total_verified_overcharge=verified_overcharge,
            total_unverified_charges=0.0,
            estimated_recoverable={"min": verified_overcharge * 0.5, "max": verified_overcharge},
            issues=issues,
            summary=f"Analyzed {len(line_items)} lab tests, found {len(issues)} issues.",
            recommendations=[
                "Verify each test was medically necessary.",
                "Compare rates with CGHS lab tariff.",
            ],
        )

    def _check_arithmetic(self, item: Dict):
        rate = item.get("rate") or 0
        qty = item.get("quantity") or 1
        amount = item.get("amount") or 0
        if not rate or not amount:
            return None
        expected = rate * qty
        if abs(expected - amount) > max(5, amount * 0.05):
            self.issue_counter += 1
            return BillingIssue(
                issue_id=f"LAB_MATH_{self.issue_counter:03d}",
                issue_type=IssueType.MISSING_ITEMIZATION,
                description=f"{item.get('description', 'Lab test')} - arithmetic mismatch",
                billed_amount=amount,
                benchmark_amount=expected,
                overcharge_amount=amount - expected,
                confidence=Confidence.MEDIUM,
                evidence=[
                    f"Rate: ₹{rate:.2f}",
                    f"Quantity: {qty}",
                    f"Expected: ₹{expected:.2f}",
                    f"Billed: ₹{amount:.2f}",
                ],
                action_required="Ask lab to clarify the rate calculation.",
                benchmark_type="ARITHMETIC",
                match_quality=0.0,
            )
        return None

    def _check_repeat_tests(self, line_items: List[Dict]) -> List[BillingIssue]:
        issues = []
        seen = {}
        for item in line_items:
            desc = (item.get("description") or "").lower().strip()
            if not desc:
                continue
            key = desc.split()[0] if desc else ""
            if key in seen:
                self.issue_counter += 1
                issues.append(BillingIssue(
                    issue_id=f"LAB_REPEAT_{self.issue_counter:03d}",
                    issue_type=IssueType.MISSING_ITEMIZATION,
                    description=f"Possible repeat test: {item.get('description')}",
                    billed_amount=item.get("amount") or 0,
                    benchmark_amount=0,
                    overcharge_amount=item.get("amount") or 0,
                    confidence=Confidence.MEDIUM,
                    evidence=[f"Similar test found earlier: {seen[key]}"],
                    action_required="Verify if both tests were medically necessary.",
                    benchmark_type="REPEAT_TEST",
                    match_quality=0.0,
                ))
            else:
                seen[key] = item.get("description")
        return issues
