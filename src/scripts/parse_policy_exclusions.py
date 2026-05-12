"""
Parse policy exclusions PDF into structured chunks for RAG.
Similar to IRDAI Master Circular chunking.
"""
import pdfplumber
import json
from pathlib import Path
import re

def extract_policy_exclusions(pdf_path: str, output_path: str):
    """Extract policy exclusions and chunk by clause."""
    
    chunks = []
    
    with pdfplumber.open(pdf_path) as pdf:
        full_text = ""
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n\n"
        
        # Split by exclusion clauses (common patterns)
        # Pattern 1: Numbered exclusions (1., 2., etc.)
        # Pattern 2: Lettered exclusions (a., b., etc.)
        # Pattern 3: "We will not pay" / "Excluded" / "Not covered"
        
        # Try numbered sections first
        sections = re.split(r'\n(\d+)\.\s+', full_text)
        
        chunk_id = 0
        for i in range(1, len(sections), 2):
            if i+1 < len(sections):
                clause_num = sections[i]
                clause_text = sections[i+1].strip()
                
                if len(clause_text) > 50:  # Skip tiny fragments
                    chunk_id += 1
                    
                    # Extract key terms for metadata
                    keywords = extract_keywords(clause_text)
                    
                    chunks.append({
                        "chunk_id": f"POL_EXCL_{chunk_id:03d}",
                        "clause_number": clause_num,
                        "text": clause_text[:2000],  # Cap at 2000 chars
                        "keywords": keywords,
                        "type": "policy_exclusion"
                    })
        
        # Fallback: if no numbered sections, chunk by paragraphs
        if len(chunks) < 5:
            paragraphs = [p.strip() for p in full_text.split('\n\n') if len(p.strip()) > 100]
            for i, para in enumerate(paragraphs, 1):
                chunks.append({
                    "chunk_id": f"POL_EXCL_{i:03d}",
                    "clause_number": str(i),
                    "text": para[:2000],
                    "keywords": extract_keywords(para),
                    "type": "policy_exclusion"
                })
    
    # Save chunks
    with open(output_path, 'w') as f:
        json.dump(chunks, f, indent=2)
    
    print(f"✅ Extracted {len(chunks)} policy exclusion chunks")
    print(f"💾 Saved to: {output_path}")
    
    return chunks

def extract_keywords(text: str) -> list:
    """Extract key medical/insurance terms from text."""
    keywords = []
    
    # Common exclusion keywords
    patterns = [
        r'pre-existing',
        r'cosmetic',
        r'dental',
        r'eyeglasses',
        r'hearing aids',
        r'experimental',
        r'not medically necessary',
        r'elective',
        r'self-inflicted',
        r'war',
        r'nuclear',
        r'suicide',
        r'intoxication',
        r'pregnancy',
        r'childbirth',
        r'infertility'
    ]
    
    text_lower = text.lower()
    for pattern in patterns:
        if re.search(pattern, text_lower):
            keywords.append(pattern)
    
    return keywords[:5]  # Top 5 keywords

if __name__ == "__main__":
    pdf_path = "data/raw/7.exclusionsPolicyClauseNewIndiaMediclaim.pdf"
    output_path = "data/reference/policy_exclusions.json"
    
    chunks = extract_policy_exclusions(pdf_path, output_path)
    
    # Show sample
    print("\nSample chunks:")
    for chunk in chunks[:3]:
        print(f"\n{chunk['chunk_id']}: Clause {chunk['clause_number']}")
        print(f"Keywords: {chunk['keywords']}")
        print(f"Text preview: {chunk['text'][:200]}...")