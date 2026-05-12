"""
Improved chunking for IRDAI Master Circular with semantic splitting.
"""
import json
import re
from pathlib import Path
from typing import List, Dict

def extract_timeline(text: str) -> List[str]:
    """Extract timeline mentions like '15 days', '1 hour', '3 hours'."""
    patterns = [
        r'\b\d+\s*(?:hour|hours|day|days|week|weeks|month|months)\b',
        r'\b(?:immediately|forthwith|without delay)\b'
    ]
    
    timelines = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        timelines.extend(matches)
    
    return list(set(timelines))

def extract_key_terms(text: str) -> List[str]:
    """Extract important insurance/regulatory terms."""
    terms = [
        'cashless', 'authorization', 'claim', 'settlement', 'reimbursement',
        'grievance', 'complaint', 'ombudsman', 'penalty', 'interest',
        'bank rate', 'policyholder', 'insurer', 'premium', 'grace period',
        'portability', 'renewal', 'pre-authorization', 'discharge'
    ]
    
    found_terms = []
    text_lower = text.lower()
    for term in terms:
        if term in text_lower:
            found_terms.append(term)
    
    return found_terms

def detect_section_heading(text: str) -> str | None:
    """Detect section headings with improved patterns."""
    lines = text.split('\n')
    
    for line in lines[:5]:  # Check first 5 lines
        line = line.strip()
        
        # Patterns for section headings
        if re.match(r'^[A-Z][A-Z\s]{10,}$', line):  # ALL CAPS
            return line
        if re.match(r'^\d+\.\s+[A-Z]', line):  # "1. Heading"
            return line
        if re.match(r'^CHAPTER\s+[A-Z\d]+', line):  # "CHAPTER VIII"
            return line
        if re.match(r'^PART\s+[A-Z\d]+', line):  # "PART A"
            return line
    
    return None

def semantic_chunk(text: str, max_chars: int = 1000) -> List[str]:
    """
    Split text semantically at natural boundaries.
    Prioritize: regulation clauses > paragraphs > sentences
    """
    chunks = []
    
    # First try splitting on numbered clauses (like "i.", "ii.", "a.", "b.")
    clause_pattern = r'\n\s*(?:[ivxlcdm]+\.|[a-z]\.|[A-Z]\.|\d+\.)\s+'
    clauses = re.split(clause_pattern, text)
    
    if len(clauses) > 1:
        # We have numbered clauses
        current_chunk = clauses[0] if clauses[0].strip() else ""
        
        for clause in clauses[1:]:
            clause = clause.strip()
            if not clause:
                continue
            
            if len(current_chunk) + len(clause) < max_chars:
                current_chunk += "\n" + clause
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = clause
        
        if current_chunk:
            chunks.append(current_chunk.strip())
    
    else:
        # Fallback to paragraph splitting
        paragraphs = re.split(r'\n\s*\n', text)
        current_chunk = ""
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            if len(current_chunk) + len(para) < max_chars:
                current_chunk += "\n\n" + para if current_chunk else para
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = para
        
        if current_chunk:
            chunks.append(current_chunk.strip())
    
    return chunks

def chunk_irdai_document(input_path: str, output_path: str):
    """Chunk IRDAI document with improved semantic splitting."""
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    chunks = []
    current_section = "Preamble"
    chunk_counter = 0
    
    print(f"Chunking {data['total_pages']} pages with semantic splitting...")
    
    for page_data in data['pages']:
        page_num = page_data['page']
        text = page_data['text']
        
        # Check for new section
        heading = detect_section_heading(text)
        if heading:
            current_section = heading
        
        # Semantic chunking
        page_chunks = semantic_chunk(text, max_chars=1000)
        
        for chunk_text in page_chunks:
            if len(chunk_text.strip()) < 100:  # Skip tiny chunks
                continue
            
            # Extract metadata
            timelines = extract_timeline(chunk_text)
            key_terms = extract_key_terms(chunk_text)
            
            chunk_counter += 1
            chunks.append({
                "chunk_id": f"irdai_chunk_{chunk_counter}",
                "text": chunk_text,
                "metadata": {
                    "source": "IRDAI Master Circular 2024",
                    "document": data['source'],
                    "reference": data['reference'],
                    "date": data['date'],
                    "page": page_num,
                    "section": current_section,
                    "timelines": timelines,
                    "key_terms": key_terms,
                    "chunk_chars": len(chunk_text)
                }
            })
    
    # Save chunks
    output = {
        "document_info": {
            "source": data['source'],
            "reference": data['reference'],
            "date": data['date'],
            "total_pages": data['total_pages']
        },
        "chunking_strategy": "semantic splitting on clauses/paragraphs, max 1000 chars",
        "total_chunks": len(chunks),
        "chunks": chunks
    }
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Created {len(chunks)} chunks")
    print(f"   Average size: {sum(c['metadata']['chunk_chars'] for c in chunks) // len(chunks)} chars")
    print(f"   Chunks with timelines: {sum(1 for c in chunks if c['metadata']['timelines'])}")
    print(f"   Saved to: {output_path}")
    
    # Show sample
    for i in range(min(2, len(chunks))):
        print(f"\n📄 Sample chunk {i+1}:")
        print(f"   Section: {chunks[i]['metadata']['section']}")
        print(f"   Timelines: {chunks[i]['metadata']['timelines']}")
        print(f"   Key terms: {chunks[i]['metadata']['key_terms'][:5]}")
        print(f"   Text: {chunks[i]['text'][:150]}...")
    
    return output

if __name__ == "__main__":
    input_path = "data/reference/irdai_master_circular_extracted.json"
    output_path = "data/reference/irdai_master_circular_chunks.json"
    
    chunk_irdai_document(input_path, output_path)