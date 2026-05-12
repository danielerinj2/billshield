"""
Modular letter sections that conditionally include based on detected issues.
"""

from typing import Dict, List, Any
from dataclasses import dataclass


@dataclass
class LetterSection:
    """A conditional section of a letter."""
    
    section_id: str
    title: str
    applies_when: callable  # Function that checks if this section applies
    content_builder: callable  # Function that builds the content
    priority: int = 0  # Higher priority sections appear first
    user_enabled: bool = True  # Can be toggled off by user


class SectionLibrary:
    """Registry of all available letter sections."""
    
    @staticmethod
    def procedure_overcharge_section(analysis_result: Dict) -> LetterSection:
        """Section for procedure overcharges (CGHS violations)."""
        
        def applies(result):
            return any(
                issue.get('issue_type') == 'procedure_overcharge' 
                for issue in result.get('issues', [])
            )
        
        def build_content(result, tone='professional'):
            issues = [
                i for i in result.get('issues', [])
                if i.get('issue_type') == 'procedure_overcharge'
            ]
            
            total_overcharge = sum(i.get('overcharge_amount', 0) for i in issues)
            
            if tone == 'polite':
                intro = "We have noticed some charges that appear higher than standard rates:"
            elif tone == 'firm':
                intro = "The following charges significantly exceed government-mandated CGHS rates:"
            else:  # professional
                intro = "Upon review, the following charges exceed CGHS benchmark rates:"
            
            content = [intro, ""]
            
            for issue in issues[:5]:  # Limit to top 5 for readability
                desc = issue.get('description', '')
                amount = issue.get('overcharge_amount', 0)
                evidence = issue.get('evidence', [])
                
                # Extract CGHS rate from evidence
                cghs_rate = "benchmark not available"
                for ev in evidence:
                    if 'CGHS rate:' in ev:
                        cghs_rate = ev.split('CGHS rate:')[1].strip()
                        break
                
                content.append(f"• {desc}")
                content.append(f"  Overcharge: ₹{amount:,.0f}")
                content.append(f"  Reference: {cghs_rate}")
                content.append("")
            
            if len(issues) > 5:
                content.append(f"...and {len(issues) - 5} additional procedure overcharges.")
                content.append("")
            
            content.append(f"Total procedure overcharges: ₹{total_overcharge:,.0f}")
            
            return "\n".join(content)
        
        return LetterSection(
            section_id="procedure_overcharge",
            title="Procedure Overcharges",
            applies_when=applies,
            content_builder=build_content,
            priority=100
        )
    
    @staticmethod
    def device_overcharge_section(analysis_result: Dict) -> LetterSection:
        """Section for device overcharges (NPPA violations)."""
        
        def applies(result):
            return any(
                issue.get('issue_type') == 'device_overcharge'
                for issue in result.get('issues', [])
            )
        
        def build_content(result, tone='professional'):
            issues = [
                i for i in result.get('issues', [])
                if i.get('issue_type') == 'device_overcharge'
            ]
            
            total = sum(i.get('overcharge_amount', 0) for i in issues)
            
            if tone == 'polite':
                intro = "Some medical devices appear to be charged above regulated prices:"
            elif tone == 'firm':
                intro = "The following devices exceed NPPA ceiling prices, violating price control regulations:"
            else:
                intro = "Medical devices have been charged above NPPA ceiling prices:"
            
            content = [intro, ""]
            
            for issue in issues:
                desc = issue.get('description', '')
                amount = issue.get('overcharge_amount', 0)
                
                content.append(f"• {desc}")
                content.append(f"  Overcharge: ₹{amount:,.0f}")
                content.append("")
            
            content.append(f"Total device overcharges: ₹{total:,.0f}")
            
            return "\n".join(content)
        
        return LetterSection(
            section_id="device_overcharge",
            title="Medical Device Overcharges",
            applies_when=applies,
            content_builder=build_content,
            priority=90
        )
    
    @staticmethod
    def multi_procedure_section(analysis_result: Dict) -> LetterSection:
        """Section for multi-procedure billing violations."""
        
        def applies(result):
            return any(
                issue.get('issue_type') == 'unbundled_charges'
                for issue in result.get('issues', [])
            )
        
        def build_content(result, tone='professional'):
            issues = [
                i for i in result.get('issues', [])
                if i.get('issue_type') == 'unbundled_charges'
            ]
            
            total = sum(i.get('overcharge_amount', 0) for i in issues)
            
            if tone == 'polite':
                intro = "We noticed multiple procedures may not have been discounted as per regulations:"
            elif tone == 'firm':
                intro = "IRDAI regulations require multi-procedure discounting (100%/50%/25%), which was not applied:"
            else:
                intro = "Multiple procedures were billed without applying mandated discounts:"
            
            content = [intro, ""]
            
            for issue in issues:
                desc = issue.get('description', '')
                amount = issue.get('overcharge_amount', 0)
                
                content.append(f"• {desc}")
                content.append(f"  Overcharge due to missing discounts: ₹{amount:,.0f}")
                content.append("")
            
            content.append(f"Total multi-procedure overcharges: ₹{total:,.0f}")
            content.append("")
            content.append("Per IRDAI guidelines: Primary procedure at 100%, second at 50%, third+ at 25%.")
            
            return "\n".join(content)
        
        return LetterSection(
            section_id="multi_procedure",
            title="Multi-Procedure Billing Violations",
            applies_when=applies,
            content_builder=build_content,
            priority=85
        )

    @staticmethod
    def drug_overcharge_section(analysis_result: Dict) -> LetterSection:
        """Section for drug overcharges (NPPA violations)."""
        
        def applies(result):
            return any(
                issue.get('issue_type') == 'drug_overcharge'
                for issue in result.get('issues', [])
            )
        
        def build_content(result, tone='professional'):
            issues = [
                i for i in result.get('issues', [])
                if i.get('issue_type') == 'drug_overcharge'
            ]
            
            total = sum(i.get('overcharge_amount', 0) for i in issues)
            
            if tone == 'polite':
                intro = "Some medications appear to be charged above regulated prices:"
            elif tone == 'firm':
                intro = "The following drugs exceed NPPA ceiling prices, violating price control regulations:"
            else:
                intro = "Medications have been charged above NPPA ceiling prices:"
            
            content = [intro, ""]
            
            for issue in issues:
                desc = issue.get('description', '')
                amount = issue.get('overcharge_amount', 0)
                
                content.append(f"• {desc}")
                content.append(f"  Overcharge: ₹{amount:,.0f}")
                content.append("")
            
            content.append(f"Total drug overcharges: ₹{total:,.0f}")
            
            return "\n".join(content)
        
        return LetterSection(
            section_id="drug_overcharge",
            title="Drug Price Violations",
            applies_when=applies,
            content_builder=build_content,
            priority=88
        )
    
    @staticmethod
    def invalid_rejection_section(analysis_result: Dict) -> LetterSection:
        """Section for invalid insurance rejections."""
        
        def applies(result):
            return any(
                issue.get('issue_type') == 'rejection_invalid'
                for issue in result.get('issues', [])
            )
        
        def build_content(result, tone='professional'):
            issues = [
                i for i in result.get('issues', [])
                if i.get('issue_type') == 'rejection_invalid'
            ]
            
            total = sum(i.get('overcharge_amount', 0) for i in issues)
            
            if tone == 'polite':
                intro = "Some items rejected by insurance may not be on IRDAI's non-payable list:"
            elif tone == 'firm':
                intro = "The insurance company rejected items that are NOT in IRDAI's official non-payable list:"
            else:
                intro = "Insurance rejected items that do not appear in IRDAI's non-payable list:"
            
            content = [intro, ""]
            
            for issue in issues:
                desc = issue.get('description', '')
                amount = issue.get('overcharge_amount', 0)
                
                content.append(f"• {desc}")
                content.append(f"  Rejected amount: ₹{amount:,.0f}")
                content.append("")
            
            content.append(f"Total potentially invalid rejections: ₹{total:,.0f}")
            content.append("")
            content.append("Note: These rejections should be reviewed with the insurance company.")
            
            return "\n".join(content)
        
        return LetterSection(
            section_id="invalid_rejection",
            title="Questionable Insurance Rejections",
            applies_when=applies,
            content_builder=build_content,
            priority=70
        )
    
    @staticmethod
    def get_all_sections() -> List[LetterSection]:
        """Return all available sections."""
        result = {}  # Use dict as placeholder
        return [
            SectionLibrary.procedure_overcharge_section(result),
            SectionLibrary.device_overcharge_section(result),
            SectionLibrary.drug_overcharge_section(result),
            SectionLibrary.multi_procedure_section(result),
            SectionLibrary.invalid_rejection_section(result),
        ]