"""
UniversalAgent - Specialized fallback agent for difficult bill matching.
Handles cases that the primary agent cannot match.
"""

import os
import json
from typing import Dict, List, Optional
from anthropic import Anthropic


class UniversalAgent:
    """
    Fallback agent that handles edge cases the primary agent misses.
    
    Strategies (in order):
    1. LLM-powered procedure matching
    2. Synonym/abbreviation expansion
    3. Amount-based heuristics
    4. Web search fallback
    5. Mark for manual review
    """
    
    def __init__(self, rag_system=None):
        self.rag = rag_system
        self.client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        self.unmatched_items = []
    
    def analyze_unmatched_items(
        self, 
        unmatched_items: List[Dict],
        bill_data: Dict
    ) -> List[Dict]:
        """
        Main entry point - analyze items the primary agent couldn't match.
        
        Args:
            unmatched_items: List of line items with no CGHS match
            bill_data: Full bill context (procedure_name, department, etc.)
        
        Returns:
            List of issues found by fallback strategies
        """
        print(f"\n{'='*70}")
        print(f"🔧 UNIVERSAL AGENT: Processing {len(unmatched_items)} unmatched items")
        print(f"{'='*70}\n")
        
        issues = []
        
        for item in unmatched_items:
            print(f"\n🔍 Analyzing unmatched: {item.get('description', 'Unknown')}")
            
            # Strategy 1: LLM-powered matching
            issue = self._llm_match_procedure(item, bill_data)
            if issue:
                issues.append(issue)
                continue
            
            # Strategy 2: Synonym expansion
            issue = self._synonym_match(item, bill_data)
            if issue:
                issues.append(issue)
                continue
            
            # Strategy 3: Amount-based heuristics
            issue = self._amount_heuristic_match(item, bill_data)
            if issue:
                issues.append(issue)
                continue
            
            # Strategy 4: Mark for manual review
            issue = self._flag_for_review(item, bill_data)
            if issue:
                issues.append(issue)
        
        print(f"\n✅ Universal Agent found {len(issues)} additional issues")
        return issues
    
    def _llm_match_procedure(self, item: Dict, bill_data: Dict) -> Optional[Dict]:
        """
        Use Claude to match procedure to CGHS benchmark.
        """
        try:
            # Get top CGHS candidates for context
            description = item.get('description', '')
            cghs_candidates = []
            
            if self.rag:
                results = self.rag.search_cghs_rates(description, n_results=10)
                cghs_candidates = [r for r in results if r.get('rate', 0) > 0][:10]
            
            if not cghs_candidates:
                return None
            
            # Build candidate list for LLM
            candidates_text = "\n".join([
                f"- {c['procedure']} (CGHS Rate: ₹{c['rate']:,.0f}, Category: {c['category']})"
                for c in cghs_candidates
            ])
            
            prompt = f"""You are a medical billing expert matching hospital charges to CGHS benchmarks.

BILL CONTEXT:
- Hospital: {bill_data.get('hospital_name', 'Unknown')}
- Department: {bill_data.get('department', 'Unknown')}
- Diagnosed Procedure: {bill_data.get('procedure_name', 'Not specified')}

LINE ITEM TO MATCH:
- Description: {description}
- Amount: ₹{item.get('amount', 0):,.0f}
- Category: {item.get('category', 'Unknown')}

POSSIBLE CGHS MATCHES:
{candidates_text}

TASK: Identify the BEST CGHS match for this line item. Consider:
1. Medical terminology equivalence (e.g., "C-Section" = "Lower Segment Caesarean Section")
2. Common abbreviations (LSCS, CABG, PTCA, TURP, etc.)
3. Procedure context from department and diagnosis
4. Logical bundling (anesthesia + surgery = main procedure rate)

Return ONLY valid JSON:
{{
  "match_found": true,
  "matched_procedure": "exact CGHS procedure name from list",
  "cghs_rate": 22000,
  "reasoning": "brief explanation",
  "confidence": "high|medium|low"
}}

If no good match exists, return:
{{
  "match_found": false,
  "reasoning": "why no match found"
}}"""

            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )
            
            result_text = response.content[0].text.strip()
            
            # Clean markdown if present
            if result_text.startswith('```json'):
                result_text = result_text.replace('```json', '').replace('```', '').strip()
            elif result_text.startswith('```'):
                result_text = result_text.replace('```', '').strip()
            
            llm_result = json.loads(result_text)
            
            if not llm_result.get('match_found'):
                print(f"  ❌ LLM: {llm_result.get('reasoning', 'No match')}")
                return None
            
            # Check if billed amount exceeds CGHS rate by significant margin
            billed_amount = item.get('amount', 0)
            cghs_rate = llm_result.get('cghs_rate', 0)
            
            if billed_amount > cghs_rate * 1.5:
                overcharge = billed_amount - cghs_rate
                
                print(f"  ✅ LLM matched: {llm_result['matched_procedure']}")
                print(f"  💰 Overcharge: ₹{overcharge:,.0f}")
                
                return {
                    'issue_id': f"UNIV_LLM_{len(self.unmatched_items):03d}",
                    'issue_type': 'procedure_overcharge',
                    'description': f"{description} exceeds CGHS benchmark (LLM matched)",
                    'billed_amount': billed_amount,
                    'benchmark_amount': cghs_rate,
                    'overcharge_amount': overcharge,
                    'confidence': llm_result.get('confidence', 'medium'),
                    'evidence': [
                        f"CGHS Procedure: {llm_result['matched_procedure']}",
                        f"CGHS Rate: ₹{cghs_rate:,.0f}",
                        f"Billed: ₹{billed_amount:,.0f}",
                        f"Markup: {((billed_amount/cghs_rate - 1) * 100):.0f}%",
                        f"LLM Reasoning: {llm_result.get('reasoning', 'N/A')}",
                        "Matched by: Universal Agent (LLM)"
                    ],
                    'action_required': f"Challenge using CGHS benchmark for {llm_result['matched_procedure']}"
                }
            
            return None
            
        except Exception as e:
            print(f"  ⚠️ LLM match failed: {e}")
            return None
    
    def _synonym_match(self, item: Dict, bill_data: Dict) -> Optional[Dict]:
        """
        Match using medical synonyms and abbreviations.
        """
        # Common medical synonyms
        synonyms = {
            'lscs': 'lower segment caesarean section',
            'c-section': 'caesarean section',
            'cabg': 'coronary artery bypass graft',
            'ptca': 'percutaneous coronary angioplasty',
            'turp': 'transurethral resection prostate',
            'tahbso': 'total abdominal hysterectomy',
            'ot': 'operation theatre',
            'icu': 'intensive care unit',
            'mri': 'magnetic resonance imaging',
            'ct': 'computed tomography',
            'echo': 'echocardiography',
            'ecg': 'electrocardiogram',
            'ekg': 'electrocardiogram',
        }
        
        description = item.get('description', '').lower()
        procedure_name = bill_data.get('procedure_name', '').lower()
        
        # Try to expand abbreviations
        expanded_query = description
        for abbr, full in synonyms.items():
            if abbr in description or abbr in procedure_name:
                expanded_query = description.replace(abbr, full)
                print(f"  🔄 Expanded '{abbr}' → '{full}'")
                break
        
        if expanded_query == description:
            return None  # No synonym found
        
        # Search with expanded query
        if self.rag:
            results = self.rag.search_cghs_rates(expanded_query, n_results=3)
            valid_results = [r for r in results if r.get('rate', 0) > 0]
            
            if valid_results:
                best = valid_results[0]
                billed_amount = item.get('amount', 0)
                cghs_rate = best.get('rate', 0)
                
                if billed_amount > cghs_rate * 1.5:
                    overcharge = billed_amount - cghs_rate
                    
                    print(f"  ✅ Synonym matched: {best['procedure']}")
                    
                    return {
                        'issue_id': f"UNIV_SYN_{len(self.unmatched_items):03d}",
                        'issue_type': 'procedure_overcharge',
                        'description': f"{item['description']} exceeds CGHS benchmark (synonym matched)",
                        'billed_amount': billed_amount,
                        'benchmark_amount': cghs_rate,
                        'overcharge_amount': overcharge,
                        'confidence': 'medium',
                        'evidence': [
                            f"CGHS Procedure: {best['procedure']}",
                            f"CGHS Rate: ₹{cghs_rate:,.0f}",
                            f"Billed: ₹{billed_amount:,.0f}",
                            f"Original term: {description}",
                            f"Expanded to: {expanded_query}",
                            "Matched by: Universal Agent (Synonym)"
                        ],
                        'action_required': f"Challenge using CGHS benchmark for {best['procedure']}"
                    }
        
        return None
    
    def _amount_heuristic_match(self, item: Dict, bill_data: Dict) -> Optional[Dict]:
        """
        Use amount range + department to estimate likely procedure.
        
        E.g., ₹85K in Cardiology = likely Angioplasty
        ₹22K in OBS-GYNE = likely C-Section
        """
        amount = item.get('amount', 0)
        department = bill_data.get('department', '').lower()
        
        # Amount-based heuristics by department
        heuristics = {
            'obs & gynecology': [
                (20000, 30000, 'Caesarean Section', 22000),
                (10000, 15000, 'Normal Delivery', 12000),
                (40000, 60000, 'Hysterectomy', 45000),
            ],
            'cardiology': [
                (70000, 120000, 'Angioplasty with Stent', 85000),
                (150000, 300000, 'CABG (Bypass)', 200000),
                (50000, 80000, 'Pacemaker Insertion', 60000),
            ],
            'orthopedics': [
                (80000, 150000, 'Knee Replacement', 120000),
                (100000, 200000, 'Hip Replacement', 150000),
                (25000, 50000, 'Fracture Fixation', 35000),
            ],
            'general surgery': [
                (25000, 45000, 'Appendectomy', 30000),
                (35000, 60000, 'Hernia Repair', 45000),
                (50000, 100000, 'Cholecystectomy', 65000),
            ],
        }
        
        if department not in heuristics:
            return None
        
        for min_amt, max_amt, procedure, cghs_rate in heuristics[department]:
            if min_amt <= amount <= max_amt * 1.5:  # Allow 50% above max
                if amount > cghs_rate * 1.5:
                    overcharge = amount - cghs_rate
                    
                    print(f"  ✅ Heuristic matched: {procedure} (₹{min_amt}-{max_amt} range)")
                    
                    return {
                        'issue_id': f"UNIV_HEUR_{len(self.unmatched_items):03d}",
                        'issue_type': 'procedure_overcharge',
                        'description': f"{item['description']} likely matches {procedure}",
                        'billed_amount': amount,
                        'benchmark_amount': cghs_rate,
                        'overcharge_amount': overcharge,
                        'confidence': 'low',  # Low confidence for heuristic match
                        'evidence': [
                            f"Estimated Procedure: {procedure}",
                            f"Estimated CGHS Rate: ₹{cghs_rate:,.0f}",
                            f"Billed: ₹{amount:,.0f}",
                            f"Matched by amount range in {department}",
                            "⚠️ Confidence: LOW - Manual verification recommended"
                        ],
                        'action_required': f"Verify procedure type and challenge if {procedure}"
                    }
        
        return None
    
    def _flag_for_review(self, item: Dict, bill_data: Dict) -> Optional[Dict]:
        """
        Flag high-value items that couldn't be matched for manual review.
        """
        amount = item.get('amount', 0)
        
        # Only flag if significant amount
        if amount < 5000:
            return None
        
        description = item.get('description', '')
        
        print(f"  📋 Flagged for manual review: {description}")
        
        return {
            'issue_id': f"UNIV_REVIEW_{len(self.unmatched_items):03d}",
            'issue_type': 'missing_itemization',
            'description': f"Unable to verify: {description}",
            'billed_amount': amount,
            'benchmark_amount': None,
            'overcharge_amount': None,
            'confidence': 'low',
            'evidence': [
                f"Amount: ₹{amount:,.0f}",
                f"Department: {bill_data.get('department', 'Unknown')}",
                "No CGHS benchmark match found",
                "Requires manual verification by patient or expert",
            ],
            'action_required': "Request itemized breakdown and verify against hospital's published rates"
        }