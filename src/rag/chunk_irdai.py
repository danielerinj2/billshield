"""
Chunk IRDAI Master Circular into retrievable segments for RAG.
"""
import json
import re
from pathlib import Path
from typing import List, Dict

def detect_section_heading(text: str) -> str | None:
    """Detect if text starts with a section heading."""
    # Common patterns: "1.", "1.1", "A.", "SECTION 1", etc.
    patterns = [
        r'^[A-Z][A-Z\s]{10,}$',  # ALL CAPS HEADINGS
        r'^\d+\.\s+[A-Z]',        # "1. Heading"
        r'^\d+\.\d+\s+[A-Z]',     # "1.1 Heading"
        r'^[A-Z]\.\s+[A-Z]',      # "A. Heading"
        r'^PART [A-Z\d]+',        # "PART A", "PART 1"
        r'^SECTION \d+',          # "SECTION 1"
    ]
    
    first_line = text.split('\n')[0].strip()
    for pattern in patterns:
        if re.match(pattern, first_line):
            return first_line
    
    return None

def chunk_by_paragraphs(text: str, max_chars: int = 2000) -> List[str]:
    """Split text into chunks by paragraphs, respecting max size."""
    # Split by double newlines (paragraphs)
    paragraphs = re.split(r'\n\s*\n', text)
    
    chunks = []
    current_chunk = []
    current_size = 0
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        para_size = len(para)
        
        # If adding this paragraph exceeds max, save current chunk
        if current_size + para_size > max_chars and current_chunk:
            chunks.append('\n\n'.join(current_chunk))
            current_chunk = [para]
            current_size = para_size
        else:
            current_chunk.append(para)
            current_size += para_size
    
    # Add final chunk
    if current_chunk:
        chunks.append('\n\n'.join(current_chunk))
    
    return chunks

def chunk_irdai_document(input_path: str, output_path: str):
    """Chunk IRDAI document into retrievable segments."""
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    chunks = []
    current_section = "Preamble"
    
    print(f"Chunking {data['total_pages']} pages...")
    
    for page_data in data['pages']:
        page_num = page_data['page']
        text = page_data['text']
        
        # Check for section heading
        heading = detect_section_heading(text)
        if heading:
            current_section = heading
        
        # Chunk this page's text
        page_chunks = chunk_by_paragraphs(text, max_chars=2000)
        
        for i, chunk_text in enumerate(page_chunks):
            chunks.append({
                "chunk_id": f"irdai_p{page_num}_c{i+1}",
                "text": chunk_text,
                "metadata": {
                    "source": "IRDAI Master Circular 2024",
                    "document": data['source'],
                    "reference": data['reference'],
                    "date": data['date'],
                    "page": page_num,
                    "section": current_section,
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
        "chunking_strategy": "paragraph-based, max 2000 chars",
        "total_chunks": len(chunks),
        "chunks": chunks
    }
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Created {len(chunks)} chunks")
    print(f"   Average chunk size: {sum(c['metadata']['chunk_chars'] for c in chunks) // len(chunks)} chars")
    print(f"   Saved to: {output_path}")
    
    # Show sample chunk
    print(f"\n📄 Sample chunk (first one):")
    print(f"   ID: {chunks[0]['chunk_id']}")
    print(f"   Section: {chunks[0]['metadata']['section']}")
    print(f"   Page: {chunks[0]['metadata']['page']}")
    print(f"   Text preview: {chunks[0]['text'][:200]}...")
    
    return output

if __name__ == "__main__":
    input_path = "data/reference/irdai_master_circular_extracted.json"
    output_path = "data/reference/irdai_master_circular_chunks.json"
    
    chunk_irdai_document(input_path, output_path)