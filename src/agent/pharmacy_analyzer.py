"""
Pharmacy Bill Analyzer
Handles retail pharmacy invoices with MRP, batch numbers, NPPA checks.
"""

from typing import Dict, List
from dataclasses import dataclass

from src.agent.core import (
    BillingIssue, AnalysisResult, IssueType, Confidence
)


class PharmacyAnalyzer:
    """Analyzes pharmacy/medical store bills."""
    
    def __init__(self, rag_system=None):
        self.rag = rag_system
        self.issue_counter = 0
    
    def analyze(self, bill_data: Dict) -> AnalysisResult:
        """
        Analyze pharmacy bill.
        
        Checks:
        - Amount > MRP (illegal)
        - Amount > NPPA ceiling (for drugs in DB)
        - Arithmetic validation (qty × rate ≈ amount)
        - Duplicate items
        - Discount math
        """
        print(f"\n{'=' * 70}")
        print("Pharmacy Bill Analyzer")
        print(f"{'=' * 70}\n")
        
        line_items = bill_data.get("line_items", [])
        total_bill = bill_data.get("total_amount", 0)
        
        print(f"📋 Analyzing {len(line_items)} pharmacy items...")
        
        issues = []
        
        # Check each item
        for item in line_items:
            # MRP check
            mrp_issue = self._check_mrp_violation(item)
            if mrp_issue:
                issues.append(mrp_issue)
            
            # NPPA check (for drugs in our database)
            nppa_issue = self._check_nppa_ceiling(item)
            if nppa_issue:
                issues.append(nppa_issue)
            
            # Arithmetic check
            arithmetic_issue = self._check_arithmetic(item)
            if arithmetic_issue:
                issues.append(arithmetic_issue)
        
        # Check for duplicates
        duplicate_issues = self._check_duplicates(line_items)
        issues.extend(duplicate_issues)
        
        # Validate totals
        total_issue = self._validate_totals(bill_data)
        if total_issue:
            issues.append(total_issue)
        
        print(f"✅ Found {len(issues)} pharmacy issues")
        
        return self._generate_result(bill_data, issues)
    
    def _check_mrp_violation(self, item: Dict) -> BillingIssue | None:
        """Check if charged amount exceeds MRP (illegal in India)."""
        description = item.get("description", "")
        amount = item.get("amount", 0)
        qty = item.get("quantity", 1)
        rate = item.get("rate", 0)
        
        # Extract MRP if available (some parsers put it in metadata)
        mrp = item.get("mrp", 0)
        if not mrp and rate:
            mrp = rate  # Often rate = MRP in pharmacy bills
        
        if not mrp or mrp == 0:
            return None
        
        # Check violation
        expected_max = mrp * qty
        tolerance = expected_max * 0.02  # 2% tolerance for rounding
        
        if amount > expected_max + tolerance:
            self.issue_counter += 1
            overcharge = amount - expected_max
            
            return BillingIssue(
                issue_id=f"MRP_{self.issue_counter:03d}",
                issue_type=IssueType.DRUG_OVERCHARGE,
                description=f"{description} charged above MRP (illegal)",
                billed_amount=amount,
                benchmark_amount=expected_max,
                overcharge_amount=overcharge,
                confidence=Confidence.HIGH,
                evidence=[
                    f"MRP: ₹{mrp:,.2f} per unit",
                    f"Quantity: {qty}",
                    f"Maximum legal price: ₹{expected_max:,.2f}",
                    f"Billed amount: ₹{amount:,.2f}",
                    f"Illegal overcharge: ₹{overcharge:,.2f}",
                    "Under Drugs (Price Control) Order 2013, retailers cannot charge above MRP",
                ],
                action_required="File complaint with Legal Metrology Department. This is a legal violation.",
                benchmark_type="MRP",
                match_quality=1.0,
                matched_procedure=description,
            )
        
        return None
    
    def _check_nppa_ceiling(self, item: Dict) -> BillingIssue | None:
        """Check if drug exceeds NPPA ceiling price."""
        if not self.rag:
            return None
        description = item.get("description", "")
        amount = item.get("amount", 0)
        qty = item.get("quantity", 1)

        
        description = item.get("description", "")
        amount = item.get("amount", 0)
        qty = item.get("quantity", 1)

        # NEW: Skip category-level summary items
        if self._is_category_summary_item(description):
            return None  # Don't try to match categories to NPPA
        
        
        # Search NPPA database
        try:
            nppa_results = self.rag.reference_collection.query(
                query_texts=[description],
                n_results=3,
                where={"type": "nppa_drug"},
            )
            
            if not nppa_results["metadatas"][0]:
                return None
            
            best_match = nppa_results["metadatas"][0][0]
            distance = nppa_results["distances"][0][0] if nppa_results["distances"] else 1.0
            similarity = 1 - distance
            
            # Only flag if similarity is decent (≥0.65)
            if similarity < 0.65:
                return None
            
            ceiling_price = best_match.get("ceiling_price", 0)
            if not ceiling_price:
                return None
            
            expected_max = ceiling_price * qty
            tolerance = expected_max * 0.1  # 10% tolerance (retailers can add margin)
            
            if amount > expected_max + tolerance:
                self.issue_counter += 1
                overcharge = amount - expected_max
                
                return BillingIssue(
                    issue_id=f"NPPA_{self.issue_counter:03d}",
                    issue_type=IssueType.DRUG_OVERCHARGE,
                    description=f"{description} may exceed NPPA ceiling price",
                    billed_amount=amount,
                    benchmark_amount=ceiling_price * qty,
                    overcharge_amount=overcharge,
                    confidence=Confidence.HIGH if similarity >= 0.8 else Confidence.MEDIUM,
                    evidence=[
                        f"NPPA ceiling: ₹{ceiling_price:,.2f} per unit",
                        f"Quantity: {qty}",
                        f"Expected maximum: ₹{expected_max:,.2f} (ceiling + 10% retail margin)",
                        f"Billed amount: ₹{amount:,.2f}",
                        f"Matched drug: {best_match.get('drug_name', 'Unknown')}",
                        f"Match confidence: {similarity:.0%}",
                    ],
                    action_required="Verify drug name matches NPPA entry. If correct, this violates NPPA ceiling price.",
                    benchmark_type="NPPA",
                    match_quality=similarity,
                    matched_procedure=best_match.get("drug_name", "Unknown"),
                )
        
        except Exception as e:
            print(f"⚠️ NPPA check failed for {description}: {e}")
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
        tolerance = max(expected * 0.05, 1)  # 5% or ₹1, whichever is larger
        
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
                action_required="Ask pharmacy to explain the calculation. May be partial pack or prorated.",
                benchmark_type="ARITHMETIC",
                match_quality=0.0,
                matched_procedure=None,
            )
        
        return None
    
    def _check_duplicates(self, line_items: List[Dict]) -> List[BillingIssue]:
        """Check for duplicate items with same batch number."""
        issues = []
        seen = {}
        
        for item in line_items:
            desc = item.get("description", "").lower().strip()
            batch = item.get("batch_no", "")
            amount = item.get("amount", 0)
            
            if not desc:
                continue
            
            key = f"{desc}_{batch}" if batch else desc
            
            if key in seen:
                self.issue_counter += 1
                prev_item = seen[key]
                
                issues.append(BillingIssue(
                    issue_id=f"DUP_{self.issue_counter:03d}",
                    issue_type=IssueType.DUPLICATE_BILLING,
                    description=f"{item.get('description', '')} appears multiple times",
                    billed_amount=amount + prev_item.get("amount", 0),
                    benchmark_amount=amount,  # Assume one is duplicate
                    overcharge_amount=amount,
                    confidence=Confidence.MEDIUM,
                    evidence=[
                        f"Item: {item.get('description', '')}",
                        f"Batch: {batch or 'Not specified'}",
                        "This item appears multiple times in the bill",
                        "May be legitimate if purchased multiple times or from different batches",
                    ],
                    action_required="Verify with pharmacy if both charges are correct",
                    benchmark_type="DUPLICATE_CHECK",
                    match_quality=0.0,
                    matched_procedure=None,
                ))
            else:
                seen[key] = item
        
        return issues
    
    def _validate_totals(self, bill_data: Dict) -> BillingIssue | None:
        """Validate gross - discount = net."""
        line_items = bill_data.get("line_items", [])
        total = bill_data.get("total_amount")
        
        # Guard: Handle missing or invalid total
        if total is None or total == 0:
            # Try to compute from line items as fallback
            calculated_sum = sum(item.get("amount", 0) for item in line_items)
            if calculated_sum == 0:
                return None  # Skip validation entirely - no usable data
            total = calculated_sum  # Use calculated as reference
        
        # Ensure total is numeric
        try:
            total = float(total)
        except (TypeError, ValueError):
            return None
        
        # Calculate sum of line items
        calculated_sum = sum(item.get("amount", 0) for item in line_items)
        
        tolerance = max(total * 0.02, 10)  # 2% or ₹10
        
        if abs(calculated_sum - total) > tolerance:
            self.issue_counter += 1
            
            return BillingIssue(
                issue_id=f"TOTAL_{self.issue_counter:03d}",
                issue_type=IssueType.MISSING_ITEMIZATION,
                description="Bill total doesn't match sum of line items",
                billed_amount=total,
                benchmark_amount=calculated_sum,
                overcharge_amount=total - calculated_sum,
                confidence=Confidence.MEDIUM,
                evidence=[
                    f"Sum of line items: ₹{calculated_sum:,.2f}",
                    f"Bill total: ₹{total:,.2f}",
                    f"Difference: ₹{abs(total - calculated_sum):,.2f}",
                    "Discount or additional charges may not be itemized",
                ],
                action_required="Request itemized breakdown of discount, taxes, or additional charges",
                benchmark_type="ARITHMETIC",
                match_quality=0.0,
                matched_procedure=None,
            )
        
        return None
    
    def _generate_result(self, bill_data: Dict, issues: List[BillingIssue]) -> AnalysisResult:
        """Generate pharmacy bill analysis result."""
        total_bill = bill_data.get("total_amount", 0)
        
        # Calculate verified overcharges (HIGH confidence only)
        verified_overcharge = sum(
            issue.overcharge_amount for issue in issues
            if issue.confidence == Confidence.HIGH and issue.overcharge_amount
        )
        
        # Unverified charges (MEDIUM/LOW confidence)
        unverified = sum(
            issue.billed_amount for issue in issues
            if issue.confidence in (Confidence.MEDIUM, Confidence.LOW)
        )
        
        high_count = sum(1 for i in issues if i.confidence == Confidence.HIGH)
        medium_count = sum(1 for i in issues if i.confidence == Confidence.MEDIUM)
        
        summary = f"Pharmacy bill analysis: Found {len(issues)} issue(s) "
        if high_count:
            summary += f"({high_count} confirmed, "
        if medium_count:
            summary += f"{medium_count} need verification). "
        if verified_overcharge:
            summary += f"Confirmed overcharges: ₹{verified_overcharge:,.2f}."
        
        recommendations = []
        if high_count > 0:
            recommendations.append(f"Challenge {high_count} confirmed violation(s) at pharmacy counter")
        if medium_count > 0:
            recommendations.append("Request clarification for items flagged for verification")
        if not issues:
            recommendations.append("No issues detected. Bill appears compliant with retail pricing rules.")
        
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
    
    def _is_category_summary_item(self, description: str) -> bool:
        """Check if this is a category summary, not an individual drug."""
        summary_keywords = [
            "medicine charges", "pharmacy charges", "drug charges",
            "total medicines", "total drugs", "consumables",
            "medical supplies"
        ]
        desc_lower = description.lower().strip()
        return any(kw in desc_lower for kw in summary_keywords)