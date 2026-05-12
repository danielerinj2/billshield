"""
Chunk user-uploaded insurance policy documents for RAG.
"""
import pdfplumber
import json
import re
from pathlib import Path
from typing import List, Dict

def extract_policy_sections(text: str) -> List[str]:
    """
    Detect common policy section keywords.
    """
    sections = [
        'exclusions', 'coverage', 'definitions', 'sub-limits', 'co-payment',
        'waiting period', 'pre-existing', 'claim procedure', 'grievance',
        'sum insured', 'room rent', 'deductible', 'copay', 'daycare',
        'ambulance', 'maternity', 'pre-hospitalization', 'post-hospitalization'
    ]
    
    found = []
    text_lower = text.lower()
    for section in sections:
        if section in text_lower:
            found.append(section)
    
    return found

def extract_monetary_limits(text: str) -> List[str]:
    """
    Extract monetary limits like '₹50,000', '₹5 lakh', 'Rs 10 lakhs'.
    """
    patterns = [
        r'₹\s*[\d,]+(?:\.\d+)?(?:\s*(?:lakh|lakhs|crore|crores))?',
        r'Rs\.?\s*[\d,]+(?:\.\d+)?(?:\s*(?:lakh|lakhs|crore|crores))?'
    ]
    
    limits = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        limits.extend(matches)
    
    return list(set(limits))

def detect_heading(text: str) -> str | None:
    """
    Detect policy section headings.
    """
    lines = text.split('\n')
    
    for line in lines[:3]:
        line = line.strip()
        
        # Common policy heading patterns
        if re.match(r'^\d+\.\s+[A-Z]', line):  # "1. COVERAGE"
            return line
        if re.match(r'^[A-Z][A-Z\s]{10,}$', line):  # ALL CAPS
            return line
        if re.match(r'^SECTION\s+[A-Z\d]+', line, re.IGNORECASE):
            return line
        if re.match(r'^CLAUSE\s+\d+', line, re.IGNORECASE):
            return line
    
    return None

def chunk_policy_text(text: str, max_chars: int = 800) -> List[str]:
    """
    Chunk policy text semantically at clause/paragraph boundaries.
    """
    # Split on numbered clauses or paragraphs
    clause_pattern = r'\n\s*(?:\d+\.|\([a-z]\)|\([ivx]+\))\s+'
    clauses = re.split(clause_pattern, text)
    
    chunks = []
    current_chunk = ""
    
    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue
        
        if len(current_chunk) + len(clause) < max_chars:
            current_chunk += "\n" + clause if current_chunk else clause
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = clause
    
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks

def chunk_policy_pdf(
    pdf_path: str,
    policy_name: str = "User Policy",
    output_path: str = None
) -> Dict:
    """
    Extract and chunk an insurance policy PDF.
    
    Args:
        pdf_path: Path to policy PDF
        policy_name: Display name for this policy
        output_path: Where to save chunks JSON (optional)
    
    Returns:
        Dict with document info and chunks
    """
    chunks = []
    chunk_counter = 0
    current_section = "General"
    
    print(f"Processing policy: {policy_name}")
    print(f"Reading PDF: {pdf_path}")
    
    with pdfplumber.open(pdf_path) as pdf:
        print(f"Extracting text from {len(pdf.pages)} pages...")
        
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            
            if not text or len(text.strip()) < 50:
                continue
            
            # Detect section heading
            heading = detect_heading(text)
            if heading:
                current_section = heading
            
            # Chunk this page
            page_chunks = chunk_policy_text(text, max_chars=800)
            
            for chunk_text in page_chunks:
                if len(chunk_text.strip()) < 100:
                    continue
                
                # Extract metadata
                sections_mentioned = extract_policy_sections(chunk_text)
                monetary_limits = extract_monetary_limits(chunk_text)
                
                chunk_counter += 1
                chunks.append({
                    "chunk_id": f"policy_chunk_{chunk_counter}",
                    "text": chunk_text,
                    "metadata": {
                        "source": "user_policy",
                        "policy_name": policy_name,
                        "page": page_num,
                        "section": current_section,
                        "sections_mentioned": sections_mentioned,
                        "monetary_limits": monetary_limits,
                        "chunk_chars": len(chunk_text)
                    }
                })
            
            if page_num % 10 == 0:
                print(f"  Processed page {page_num}/{len(pdf.pages)}")
    
    output = {
        "policy_info": {
            "name": policy_name,
            "source_file": pdf_path,
            "total_pages": page_num,
            "total_chunks": len(chunks)
        },
        "chunks": chunks
    }
    
    # Save if output path provided
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"\n✅ Saved {len(chunks)} chunks to: {output_path}")
    
    print(f"\n📊 Policy Chunking Summary:")
    print(f"   Total chunks: {len(chunks)}")
    print(f"   Avg chunk size: {sum(c['metadata']['chunk_chars'] for c in chunks) // len(chunks)} chars")
    print(f"   Chunks with exclusions: {sum(1 for c in chunks if 'exclusions' in c['metadata']['sections_mentioned'])}")
    print(f"   Chunks with monetary limits: {sum(1 for c in chunks if c['metadata']['monetary_limits'])}")
    
    # Sample
    if chunks:
        print(f"\n📄 Sample chunk:")
        print(f"   Section: {chunks[0]['metadata']['section']}")
        print(f"   Sections mentioned: {chunks[0]['metadata']['sections_mentioned']}")
        print(f"   Text: {chunks[0]['text'][:200]}...")
    
    return output

if __name__ == "__main__":
    # Test with synthetic policy (we'll create one)
    print("⚠️  No test policy found.")
    print("   Create a test policy PDF or run: chunk_policy_pdf('path/to/policy.pdf', 'My Policy')")