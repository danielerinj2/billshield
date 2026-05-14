cat > /Users/erin/billshield/src/agent/lab_analyzer.py << 'EOF'
"""
Lab Bill Analyzer
Handles diagnostic laboratory test bills with CGHS rate benchmarking.
"""

from typing import Dict, List
from collections import defaultdict

from src.agent.core import (
    BillingIssue, AnalysisResult, IssueType, Confidence
)


class LabAnalyzer:
    """Analyzes diagnostic lab test bills."""
    
    def __init__(self, rag_system=None):
        self.rag = rag_system
        self.issue_counter = 0
    
    def analyze(self, bill_data: Dict) -> AnalysisResult:
        """Analyze lab bill."""
        print(f"\n{'=' * 70}")
        print("Lab Bill Analyzer")
        print(f"{'=' * 70}\n")
        
        line_items = bill_data.get("line_items", [])
        total_bill = bill_data.get("total_amount", 0)
        
        print(f"🔬 Analyzing {len(line_items)} lab tests...")
        
        issues = []
        
        for item in line_items:
            cghs_issue = self._check_cghs_rate(item)
            if cghs_issue:
                issues.append(cghs_issue)
            
            arithmetic_issue = self._check_arithmetic(item)
            if arithmetic_issue:
                issues.append(arithmetic_issue)
        
        repeat_issues = self._check_repeat_tests(line_items)
        issues.extend(repeat_issues)
        
        bundle_issue = self._check_bundle_pricing(line_items)
        if bundle_issue:
            issues.append(bundle_issue)
        
        total_issue = self._validate_totals(bill_data)
        if total_issue:
            issues.append(total_issue)
        
        print(f"✅ Found {len(issues)} lab billing issues")
        
        return self._generate_result(bill_data, issues)
    
    def _check_cghs_rate(self, item: Dict) -> BillingIssue | None:
        """Check test price against CGHS benchmark."""
        if not self.rag:
            return None
        
        description = item.get("description", "")
        amount = item.get("amount", 0)
        qty = item.get("quantity", 1)
        
        try:
            cghs_results = self.rag.reference_collection.query(
                query_texts=[description],
                n_results=3,
                where={"type": "cghs_rate"},
            )
            
            if not cghs_results["metadatas"][0]:
                return None
            
            best_match = cghs_results["metadatas"][0][0]
            distance = cghs_results["distances"][0][0] if cghs_results["distances"] else 1.0
            similarity = 1 - distance
            
            if similarity < 0.70:
                return None
            
            category = best_match.get("category", "").lower()
            if "investigation" not in category and "lab" not in category:
                return None
            
            cghs_rate = best_match.get("rate", 0)
            if not cghs_rate:
                return None
            
            rate_per_test = amount / qty if qty > 0 else amount
            cghs_benchmark = cghs_rate
            tolerance = cghs_benchmark * 0.10
            
            if rate_per_test > cghs_benchmark + tolerance:
                self.issue_counter += 1
                overcharge_per_test = rate_per_test - cghs_benchmark
                total_overcharge = overcharge_per_test * qty
                
                confidence = Confidence.HIGH if similarity >= 0.85 else Confidence.MEDIUM
                
                return BillingIssue(
                    issue_id=f"LAB_{self.issue_counter:03d}",
                    issue_type=IssueType.PROCEDURE_OVERCHARGE,
                    description=f"{description} exceeds CGHS rate",
                    billed_amount=amount,
                    benchmark_amount=cghs_benchmark * qty,
                    overcharge_amount=total_overcharge,
                    confidence=confidence,
                    evidence=[
                        f"CGHS rate: ₹{cghs_benchmark:,.2f} per test",
                        f"Billed rate: ₹{rate_per_test:,.2f} per test",
                        f"Quantity: {qty}",
                        f"Total overcharge: ₹{total_overcharge:,.2f}",
                        f"Matched test: {best_match.get('procedure_name', 'Unknown')}",
                        f"Match confidence: {similarity:.0%}",
                    ],
                    action_required="Request explanation for charges above CGHS rate. Lab tests are typically reimbursed at CGHS rates.",
                    benchmark_type="CGHS",
                    match_quality=similarity,
                    matched_procedure=best_match.get("procedure_name", "Unknown"),
                )
        
        except Exception as e:
            print(f"⚠️ CGHS check failed for {description}: {e}")
            return None
        
        return None
    
    def _check_arithmetic(self, item: Dict) -> BillingIssue | None:
        """Check if qty × rate ≈ amount."""
        description = item.get("description", "")
        amount = item.get("amount", 0)
        qty = item.get("quantity", 1)
        rate = item.get("rate", 0)
        
        if not rate or not qty:
            return None
        
        expected = rate * qty
        tolerance = max(expected * 0.05, 5)
        
        if abs(amount - expected) > tolerance:
            self.issue_counter += 1
            
            return BillingIssue(
                issue_id=f"MATH_{self.issue_counter:03d}",
                issue_type=IssueType.MISSING_ITEMIZATION,
                description=f"{description} - arithmetic doesn't match",
                billed_amount=amount,
                benchmark_amount=expected,
                overcharge_amount=amount - expected,
                confidence=Confidence.MEDIUM,
                evidence=[
                    f"Rate: ₹{rate:,.2f}",
                    f"Quantity: {qty}",
                    f"Expected (rate × qty): ₹{expected:,.2f}",
                    f"Billed amount: ₹{amount:,.2f}",
                    f"Discrepancy: ₹{abs(amount - expected):,.2f}",
                ],
                action_required="Ask lab to explain the calculation.",
                benchmark_type="ARITHMETIC",
                match_quality=0.0,
                matched_procedure=None,
            )
        
        return None
    
    def _check_repeat_tests(self, line_items: List[Dict]) -> List[BillingIssue]:
        """Check for duplicate/repeat tests in same bill."""
        issues = []
        test_counts = defaultdict(list)
        
        for idx, item in enumerate(line_items):
            desc = item.get("description", "").lower().strip()
            if not desc:
                continue
            
            desc_normalized = desc.replace("test", "").replace("investigation", "").strip()
            test_counts[desc_normalized].append((idx, item))
        
        for test_name, occurrences in test_counts.items():
            if len(occurrences) > 1:
                self.issue_counter += 1
                total_amount = sum(item.get("amount", 0) for _, item in occurrences)
                avg_amount = total_amount / len(occurrences)
                
                original_names = [item.get("description", "") for _, item in occurrences]
                
                issues.append(BillingIssue(
                    issue_id=f"REPEAT_{self.issue_counter:03d}",
                    issue_type=IssueType.DUPLICATE_BILLING,
                    description=f"{original_names[0]} appears {len(occurrences)} times",
                    billed_amount=total_amount,
                    benchmark_amount=avg_amount,
                    overcharge_amount=total_amount - avg_amount,
                    confidence=Confidence.MEDIUM,
                    evidence=[
                        f"Test: {original_names[0]}",
                        f"Appears {len(occurrences)} times in bill",
                        f"Total charged: ₹{total_amount:,.2f}",
                        "May be legitimate if test was repeated due to inconclusive results",
                    ],
                    action_required="Verify if repeat testing was medically necessary. Request clinical justification.",
                    benchmark_type="DUPLICATE_CHECK",
                    match_quality=0.0,
                    matched_procedure=None,
                ))
        
        return issues
    
    def _check_bundle_pricing(self, line_items: List[Dict]) -> BillingIssue | None:
        """Check if individual tests could have been bundled cheaper."""
        BUNDLE_KEYWORDS = {
            "full body": ["cbc", "lipid", "glucose", "thyroid", "liver", "kidney"],
            "comprehensive": ["cbc", "lipid", "glucose", "liver", "kidney"],
            "basic metabolic": ["glucose", "electrolyte", "creatinine"],
            "lipid profile": ["cholesterol", "triglyceride", "hdl", "ldl"],
        }
        
        has_bundle = any(
            any(keyword in item.get("description", "").lower() for keyword in BUNDLE_KEYWORDS.keys())
            for item in line_items
        )
        
        if has_bundle:
            return None
        
        test_descriptions = [item.get("description", "").lower() for item in line_items]
        
        for bundle_name, components in BUNDLE_KEYWORDS.items():
            matches = sum(
                1 for component in components
                if any(component in desc for desc in test_descriptions)
            )
            
            if matches >= 4:
                self.issue_counter += 1
                total_individual = sum(
                    item.get("amount", 0) for item in line_items
                    if any(component in item.get("description", "").lower() for component in components)
                )
                
                estimated_bundle_price = total_individual * 0.70
                estimated_savings = total_individual - estimated_bundle_price
                
                return BillingIssue(
                    issue_id=f"BUNDLE_{self.issue_counter:03d}",
                    issue_type=IssueType.UNBUNDLED_CHARGES,
                    description=f"Individual tests could be bundled as '{bundle_name}' package",
                    billed_amount=total_individual,
                    benchmark_amount=estimated_bundle_price,
                    overcharge_amount=estimated_savings,
                    confidence=Confidence.LOW,
                    evidence=[
                        f"Found {matches} components of '{bundle_name}' package",
                        f"Billed individually: ₹{total_individual:,.2f}",
                        f"Typical bundle price: ₹{estimated_bundle_price:,.2f} (est.)",
                        f"Potential savings: ₹{estimated_savings:,.2f}",
                        "Note: Bundle pricing varies by lab",
                    ],
                    action_required="Ask if bundle pricing was available. For future, request package rates upfront.",
                    benchmark_type="BUNDLE_PRICING",
                    match_quality=0.0,
                    matched_procedure=None,
                )
        
        return None
    
    def _validate_totals(self, bill_data: Dict) -> BillingIssue | None:
        """Validate bill total matches sum of line items."""
        line_items = bill_data.get("line_items", [])
        total = bill_data.get("total_amount")
        
        if total is None or total == 0:
            calculated_sum = sum(item.get("amount", 0) for item in line_items)
            if calculated_sum == 0:
                return None
            total = calculated_sum
        
        try:
            total = float(total)
        except (TypeError, ValueError):
            return None
        
        calculated_sum = sum(item.get("amount", 0) for item in line_items)
        tolerance = max(total * 0.02, 10)
        
        if abs(calculated_sum - total) > tolerance:
            self.issue_counter += 1
            
            return BillingIssue(
                issue_id=f"TOTAL_{self.issue_counter:03d}",
                issue_type=IssueType.MISSING_ITEMIZATION,
                description="Bill total doesn't match sum of test charges",
                billed_amount=total,
                benchmark_amount=calculated_sum,
                overcharge_amount=total - calculated_sum,
                confidence=Confidence.MEDIUM,
                evidence=[
                    f"Sum of test charges: ₹{calculated_sum:,.2f}",
                    f"Bill total: ₹{total:,.2f}",
                    f"Difference: ₹{abs(total - calculated_sum):,.2f}",
                    "May include collection charges, home visit fees, or processing fees",
                ],
                action_required="Request itemized breakdown of all charges beyond test fees",
                benchmark_type="ARITHMETIC",
                match_quality=0.0,
                matched_procedure=None,
            )
        
        return None
    
    def _generate_result(self, bill_data: Dict, issues: List[BillingIssue]) -> AnalysisResult:
        """Generate lab bill analysis result."""
        total_bill = bill_data.get("total_amount", 0)
        
        verified_overcharge = sum(
            issue.overcharge_amount for issue in issues
            if issue.confidence == Confidence.HIGH and issue.overcharge_amount
        )
        
        unverified = sum(
            issue.billed_amount for issue in issues
            if issue.confidence in (Confidence.MEDIUM, Confidence.LOW)
        )
        
        high_count = sum(1 for i in issues if i.confidence == Confidence.HIGH)
        medium_count = sum(1 for i in issues if i.confidence == Confidence.MEDIUM)
        low_count = sum(1 for i in issues if i.confidence == Confidence.LOW)
        
        summary = f"Lab bill analysis: Found {len(issues)} issue(s) "
        if high_count:
            summary += f"({high_count} above CGHS rates, "
        if medium_count:
            summary += f"{medium_count} need verification, "
        if low_count:
            summary += f"{low_count} potential savings). "
        if verified_overcharge:
            summary += f"Confirmed overcharges: ₹{verified_overcharge:,.2f}."
        
        recommendations = []
        if high_count > 0:
            recommendations.append(f"Challenge {high_count} test(s) exceeding CGHS rates")
        if medium_count > 0:
            recommendations.append("Request clarification for flagged tests")
        if low_count > 0:
            recommendations.append("Consider package/bundle rates for future testing")
        if not issues:
            recommendations.append("No issues detected. Lab charges appear within CGHS benchmarks.")
        
        return AnalysisResult(
            total_bill=total_bill,
            total_approved=0,
            total_rejected=0,
            total_patient_liability=total_bill,
            total_verified_overcharge=verified_overcharge,
            total_unverified_charges=unverified,
            estimated_recoverable={"min": verified_overcharge, "max": verified_overcharge},
            issues=issues,
            summary=summary,
            recommendations=recommendations,
        )
EOF