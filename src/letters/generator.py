cat > src/letters/generator.py << 'PYEOF'
"""
Adaptive Letter Generator - dynamically builds letters based on detected issues.
Improved for Indian medical billing context with calibrated, evidence-based language.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Literal

from src.letters.sections import SectionLibrary


ToneType = Literal['polite', 'professional', 'firm']


class AdaptiveLetterGenerator:
    """Generates letters that adapt to detected issues."""
    
    def __init__(self, analysis_result: Dict):
        self.analysis = analysis_result
        self.available_sections = SectionLibrary.get_all_sections()
    
    def generate_hospital_letter(
        self,
        tone: ToneType = 'professional',
        patient_name: str = "[Patient Name]",
        hospital_name: str = "[Hospital Name]",
        bill_number: str = "[Bill Number]"
    ) -> str:
        """Generate hospital letter calibrated to Indian billing context."""
        
        parts = []
        parts.append("REQUEST FOR REVIEW AND RECTIFICATION OF HOSPITAL BILL")
        parts.append("=" * 60)
        parts.append("")
        parts.append(f"Date: {datetime.now().strftime('%B %d, %Y')}")
        parts.append(f"Patient Name: {patient_name}")
        parts.append(f"Bill Number: {bill_number}")
        parts.append(f"Total Bill Amount: Rs. {self.analysis.get('total_bill', 0):,.0f}")
        parts.append("")
        parts.append(f"To: The Billing Department")
        parts.append(f"{hospital_name}")
        parts.append("")
        parts.append(f"Subject: Request for Review and Rectification of Bill No. {bill_number}")
        parts.append("")
        
        # Opening
        if tone == 'polite':
            parts.append("Dear Sir/Madam,")
            parts.append("")
            parts.append(
                "Thank you for the care provided during my treatment. After reviewing "
                "my hospital bill, I have identified a few items that require review "
                "and clarification. I am writing to request your assistance in resolving these."
            )
        elif tone == 'firm':
            parts.append("Dear Sir/Madam,")
            parts.append("")
            parts.append(
                "I am writing to formally request a review and rectification of the "
                "above-referenced hospital bill. Specific charges appear to exceed "
                "applicable benchmarks and require itemized justification."
            )
        else:
            parts.append("Dear Sir/Madam,")
            parts.append("")
            parts.append(
                "After a careful review of the above-referenced bill, I have identified "
                "items that require justification or correction. I am writing to formally "
                "request a review under your standard billing grievance process."
            )
        parts.append("")
        
        # Separate issues by confidence
        issues = self.analysis.get('issues', [])
        high_conf = [i for i in issues if i.get('confidence') == 'high']
        medium_conf = [i for i in issues if i.get('confidence') == 'medium']
        low_conf = [i for i in issues if i.get('confidence') == 'low']
        
        # SECTION 1: Verified overcharges (high confidence only)
        if high_conf:
            parts.append("SECTION A — CHARGES REQUIRING IMMEDIATE RECTIFICATION:")
            parts.append("(These items appear to exceed published benchmarks)")
            parts.append("")
            for idx, issue in enumerate(high_conf, 1):
                desc = issue.get('description', '').replace(' (illegal)', '').replace(' charged above MRP', ' — exceeds reference price')
                overcharge = issue.get('overcharge_amount', 0)
                benchmark = issue.get('benchmark_amount')
                billed = issue.get('billed_amount', 0)
                
                parts.append(f"{idx}. {desc}")
                parts.append(f"   Billed: Rs. {billed:,.2f}")
                if benchmark:
                    parts.append(f"   Reference benchmark: Rs. {benchmark:,.2f}")
                parts.append(f"   Excess over reference: Rs. {overcharge:,.2f}")
                parts.append("")
            
            total_high = sum(i.get('overcharge_amount', 0) for i in high_conf)
            parts.append(f"Subtotal of charges requiring rectification: Rs. {total_high:,.2f}")
            parts.append("")
        
        # SECTION 2: Items needing clarification (medium + low confidence)
        clarification_items = medium_conf + low_conf
        if clarification_items:
            parts.append("SECTION B — ITEMS REQUIRING CLARIFICATION:")
            parts.append("(These charges could not be fully reconciled against available benchmarks)")
            parts.append("")
            for idx, issue in enumerate(clarification_items, 1):
                desc = issue.get('description', '')
                billed = issue.get('billed_amount', 0)
                parts.append(f"{idx}. {desc}")
                if billed:
                    parts.append(f"   Billed: Rs. {billed:,.2f}")
                parts.append("")
            
            # ONE consolidated request instead of repeating per item
            parts.append("For the items in Section B, kindly provide:")
            parts.append("   a) The exact item/procedure name and applicable tariff code")
            parts.append("   b) The hospital's published tariff or MRP/NPPA reference (where applicable)")
            parts.append("   c) Pack size, batch, and GST treatment (for medicines/consumables)")
            parts.append("   d) A breakdown if charged as part of a package")
            parts.append("")
        
        # Documents requested
        parts.append("DOCUMENTS REQUESTED:")
        parts.append("")
        parts.append("Please provide the following within 15 days:")
        parts.append("1. A fully itemized bill with tariff/procedure codes for each line item")
        parts.append("2. Written justification for any charges retained as billed")
        parts.append("3. A corrected bill reflecting any agreed adjustments")
        parts.append("4. Refund or credit note for any confirmed excess charges")
        parts.append("")
        
        # Escalation path
        parts.append("ESCALATION:")
        parts.append("")
        if tone == 'firm':
            parts.append("If this matter is not resolved within 15 days, I will escalate to:")
        else:
            parts.append("If unresolved within 15 days, I reserve the right to escalate to:")
        parts.append("   - The hospital's grievance redressal officer")
        parts.append("   - My insurer's grievance cell (if claim is involved)")
        parts.append("   - District Consumer Disputes Redressal Commission")
        parts.append("   - State Health Authority under the Clinical Establishments Act (where applicable)")
        parts.append("   - IRDAI Bima Bharosa portal (for insurance-linked disputes)")
        parts.append("")
        
        # Closing
        parts.append(
            "I appreciate your prompt attention to this matter. I am happy to provide "
            "any additional documentation needed to facilitate the review."
        )
        parts.append("")
        parts.append("Yours sincerely,")
        parts.append("")
        parts.append("")
        parts.append(patient_name)
        parts.append("")
        parts.append("Enclosures: Copy of original bill, BillShield analysis report")
        parts.append("")
        parts.append("---")
        parts.append("Note: Reference price comparisons are based on publicly available CGHS, NPPA, and MRP data.")
        parts.append("This letter is a request for review and not a legal determination of wrongdoing.")
        
        return "\n".join(parts)
    
    def generate_hospital_clarification_letter(
        self,
        patient_name: str = "[Patient Name]",
        hospital_name: str = "[Hospital Name]",
        bill_number: str = "[Bill Number]"
    ) -> str:
        """Polite clarification request for low-confidence issues only."""
        
        parts = []
        parts.append("REQUEST FOR BILL CLARIFICATION")
        parts.append("=" * 60)
        parts.append("")
        parts.append(f"Date: {datetime.now().strftime('%B %d, %Y')}")
        parts.append(f"Patient Name: {patient_name}")
        parts.append(f"Bill Number: {bill_number}")
        parts.append(f"Total Bill Amount: Rs. {self.analysis.get('total_bill', 0):,.0f}")
        parts.append("")
        parts.append(f"To: The Billing Department")
        parts.append(f"{hospital_name}")
        parts.append("")
        parts.append(f"Subject: Request for Clarification on Bill No. {bill_number}")
        parts.append("")
        parts.append("Dear Sir/Madam,")
        parts.append("")
        parts.append(
            "Thank you for the medical care provided. I am writing to request "
            "clarification on a few items in my bill for my personal records and "
            "potential insurance reimbursement. This is not an allegation of incorrect "
            "billing — I simply need item-level details to reconcile the charges."
        )
        parts.append("")
        
        issues = self.analysis.get('issues', [])
        clarification_issues = [i for i in issues if i.get('confidence') in ['low', 'medium']]
        
        if clarification_issues:
            parts.append("ITEMS REQUIRING CLARIFICATION:")
            parts.append("")
            for idx, issue in enumerate(clarification_issues, 1):
                desc = issue.get('description', '')
                billed = issue.get('billed_amount', 0)
                parts.append(f"{idx}. {desc}")
                if billed:
                    parts.append(f"   Amount: Rs. {billed:,.2f}")
                parts.append("")
            
            parts.append("For each of the above items, kindly provide:")
            parts.append("   a) The exact procedure/item name and tariff/procedure code")
            parts.append("   b) Whether this is a packaged charge and the package contents")
            parts.append("   c) Your hospital's published tariff for the item")
            parts.append("   d) Pack size and GST treatment (for medicines/consumables)")
            parts.append("")
        
        parts.append("REQUESTED ACTION:")
        parts.append("")
        parts.append("Kindly provide these details in writing within 14 days, ideally on")
        parts.append("hospital letterhead via email or post.")
        parts.append("")
        parts.append("Thank you for your assistance.")
        parts.append("")
        parts.append("Yours sincerely,")
        parts.append("")
        parts.append(patient_name)
        
        return "\n".join(parts)
    
    def generate_insurer_letter(
        self,
        tone: ToneType = 'firm',
        patient_name: str = "[Patient Name]",
        insurer_name: str = "[Insurance Company]",
        policy_number: str = "[Policy Number]",
        claim_number: str = "[Claim Number]"
    ) -> str:
        """Insurer escalation letter aligned with IRDAI grievance process."""
        
        parts = []
        parts.append("INSURANCE CLAIM GRIEVANCE — ESCALATION")
        parts.append("=" * 60)
        parts.append("")
        parts.append(f"Date: {datetime.now().strftime('%B %d, %Y')}")
        parts.append(f"Policy Number: {policy_number}")
        parts.append(f"Claim Number: {claim_number}")
        parts.append(f"Policyholder: {patient_name}")
        parts.append("")
        parts.append(f"To: The Grievance Redressal Officer")
        parts.append(f"{insurer_name}")
        parts.append("")
        parts.append("Subject: Escalation of Claim Settlement — Request for Review under IRDAI Guidelines")
        parts.append("")
        
        if tone == 'polite':
            parts.append("Dear Sir/Madam,")
            parts.append("")
            parts.append(
                "I am writing to respectfully request a review of my claim settlement. "
                "Certain deductions or rejections do not appear consistent with my policy "
                "terms or applicable IRDAI guidelines."
            )
        elif tone == 'firm':
            parts.append("Dear Sir/Madam,")
            parts.append("")
            parts.append(
                "I am formally escalating concerns regarding my claim settlement. "
                "Several items appear inconsistent with my policy terms and IRDAI's "
                "Protection of Policyholders' Interests Regulations."
            )
        else:
            parts.append("Dear Sir/Madam,")
            parts.append("")
            parts.append(
                "I am writing to escalate concerns regarding my claim settlement. "
                "Certain rejected or short-paid items require review against my policy "
                "terms and IRDAI's regulatory framework."
            )
        parts.append("")
        
        # Financial summary
        total_claim = self.analysis.get('total_bill', 0)
        approved = self.analysis.get('total_approved', 0)
        rejected = self.analysis.get('total_rejected', 0)
        
        parts.append("CLAIM SUMMARY:")
        parts.append(f"   Total Claim Amount: Rs. {total_claim:,.0f}")
        parts.append(f"   Amount Approved:    Rs. {approved:,.0f}")
        parts.append(f"   Amount Rejected:    Rs. {rejected:,.0f}")
        parts.append("")
        
        rejection_issues = [
            i for i in self.analysis.get('issues', [])
            if i.get('issue_type') in ['rejection_invalid', 'rejection_delayed', 'policy_violation']
        ]
        
        if rejection_issues:
            parts.append("ITEMS REQUIRING REVIEW:")
            parts.append("")
            for idx, issue in enumerate(rejection_issues, 1):
                desc = issue.get('description', '')
                amount = issue.get('overcharge_amount', 0)
                evidence = issue.get('evidence', [])
                
                parts.append(f"{idx}. {desc}")
                if amount > 0:
                    parts.append(f"   Amount: Rs. {amount:,.0f}")
                for ev in evidence[:2]:
                    parts.append(f"   - {ev}")
                parts.append("")
        
        parts.append("REGULATORY FRAMEWORK:")
        parts.append("   - IRDAI (Protection of Policyholders' Interests) Regulations, 2017")
        parts.append("   - IRDAI Master Circular on Health Insurance Business, 2024")
        parts.append("   - My policy terms and conditions (copy enclosed)")
        parts.append("")
        
        parts.append("REQUESTED ACTION:")
        parts.append("")
        parts.append("Within 15 working days, kindly provide:")
        parts.append("1. Itemized basis for each rejection or deduction")
        parts.append("2. Reference to the specific policy clause invoked")
        parts.append("3. Settlement of items that do not have a valid policy basis")
        parts.append("4. A written response confirming the outcome")
        parts.append("")
        
        parts.append("ESCALATION PATH:")
        parts.append("")
        parts.append("If this matter is not satisfactorily resolved within 15 working days, I will escalate to:")
        parts.append("   - IRDAI Integrated Grievance Management System (IGMS)")
        parts.append("   - Bima Bharosa portal (bimabharosa.irdai.gov.in)")
        parts.append("   - The Insurance Ombudsman for my region")
        parts.append("")
        parts.append("Thank you for your prompt attention to this matter.")
        parts.append("")
        parts.append("Yours sincerely,")
        parts.append("")
        parts.append(patient_name)
        
        return "\n".join(parts)
    
    def generate_patient_summary(
        self,
        patient_name: str = "[Patient Name]",
        scenario: str = "A_cash_clarification"
    ) -> str:
        """Patient-facing summary with action plan."""
        
        parts = []
        parts.append("BILLSHIELD ANALYSIS REPORT")
        parts.append("=" * 70)
        parts.append("")
        parts.append(
            "This report compares your bill against publicly available government "
            "benchmarks (CGHS, NPPA, MRP). It is intended as evidence for negotiation "
            "and is not a legal determination."
        )
        parts.append("")
        parts.append(f"Patient: {patient_name}")
        parts.append(f"Analysis Date: {datetime.now().strftime('%B %d, %Y')}")
        parts.append("")
        parts.append("=" * 70)
        parts.append("")
        
        total_bill = self.analysis.get('total_bill', 0)
        verified = self.analysis.get('total_verified_overcharge', 0)
        
        parts.append("FINANCIAL OVERVIEW:")
        parts.append("-" * 70)
        parts.append(f"   Total Bill:              Rs. {total_bill:,.0f}")
        parts.append(f"   Verified Excess:         Rs. {verified:,.0f}")
        parts.append("")
        
        issues = self.analysis.get('issues', [])
        high_conf = [i for i in issues if i.get('confidence') == 'high']
        medium_conf = [i for i in issues if i.get('confidence') == 'medium']
        low_conf = [i for i in issues if i.get('confidence') == 'low']
        
        if high_conf:
            parts.append(f"VERIFIED EXCESS CHARGES ({len(high_conf)}):")
            parts.append("-" * 70)
            for issue in high_conf[:10]:
                desc = issue.get('description', '').replace(' (illegal)', '')
                amount = issue.get('overcharge_amount', 0)
                parts.append(f"   - {desc}")
                parts.append(f"     Excess: Rs. {amount:,.0f}")
            parts.append("")
        
        if medium_conf:
            parts.append(f"ITEMS NEEDING VERIFICATION ({len(medium_conf)}):")
            parts.append("-" * 70)
            for issue in medium_conf[:10]:
                parts.append(f"   - {issue.get('description', '')}")
            parts.append("")
        
        if low_conf:
            parts.append(f"ITEMS NEEDING CLARIFICATION ({len(low_conf)}):")
            parts.append("-" * 70)
            for issue in low_conf[:10]:
                parts.append(f"   - {issue.get('description', '')}")
            parts.append("")
        
        parts.append("=" * 70)
        parts.append("")
        parts.append("RECOMMENDED ACTIONS:")
        parts.append("")
        parts.append("STEP 1 (Within 7 days):")
        parts.append("   Send the enclosed letter to the hospital billing department.")
        parts.append("   Use registered post or email with delivery confirmation.")
        parts.append("   Attach a copy of this BillShield report.")
        parts.append("")
        parts.append("STEP 2 (After 15 days, if no response):")
        parts.append("   - Approach the hospital's grievance redressal officer")
        parts.append("   - If insurance is involved: file grievance with insurer's grievance cell")
        parts.append("   - Submit a complaint at bimabharosa.irdai.gov.in (for claim issues)")
        parts.append("")
        parts.append("STEP 3 (If still unresolved):")
        parts.append("   - File at District Consumer Disputes Redressal Commission")
        parts.append("   - Approach the Insurance Ombudsman (for claim-related disputes)")
        parts.append("   - Report to State Health Authority under Clinical Establishments Act")
        parts.append("")
        parts.append("DOCUMENTS TO KEEP READY:")
        parts.append("   - Original hospital bills and payment receipts")
        parts.append("   - Discharge summary")
        parts.append("   - This BillShield analysis report")
        parts.append("   - Proof of letter delivery (postal receipt or email confirmation)")
        parts.append("   - Insurance policy document and claim correspondence (if applicable)")
        parts.append("")
        parts.append("=" * 70)
        parts.append("Generated by BillShield — Medical Bill Auditor")
        
        return "\n".join(parts)
    
    def _build_confidence_based_language(self) -> str:
        """Legacy helper, kept for backward compatibility."""
        return ""
    
    def _get_applicable_sections(self) -> List:
        return [
            section for section in self.available_sections
            if section.applies_when(self.analysis) and section.user_enabled
        ]
    
    def _build_regulatory_references(self) -> str:
        cited_regs = set()
        for issue in self.analysis.get('issues', []):
            for evidence in issue.get('evidence', []):
                if 'CGHS' in evidence:
                    cited_regs.add("- CGHS Rate Schedule (Central Government Health Scheme)")
                if 'NPPA' in evidence:
                    cited_regs.add("- NPPA Price Control Orders")
                if 'IRDAI' in evidence:
                    cited_regs.add("- IRDAI Master Circular 2024")
        return "\n".join(sorted(cited_regs))


def generate_all_letters(analysis_result_path: Path, output_dir: Path, tone: ToneType = 'professional'):
    """Generate letters from an analysis result JSON."""
    with open(analysis_result_path, 'r') as f:
        analysis = json.load(f)
    generator = AdaptiveLetterGenerator(analysis)
    output_dir.mkdir(parents=True, exist_ok=True)
    hospital_letter = generator.generate_hospital_letter(tone=tone)
    (output_dir / 'hospital_objection_letter.txt').write_text(hospital_letter)
    print(f"Generated hospital letter ({tone} tone)")
PYEOF