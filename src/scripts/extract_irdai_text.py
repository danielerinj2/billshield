"""
Extract text from IRDAI Master Circular PDF with page metadata.
"""
import pdfplumber
import json
from pathlib import Path

def extract_irdai_text(pdf_path: str, output_path: str):
    """Extract text from IRDAI PDF, preserving page structure."""
    pages_data = []
    
    with pdfplumber.open(pdf_path) as pdf:
        print(f"Extracting text from {len(pdf.pages)} pages...")
        
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            
            if text and text.strip():
                pages_data.append({
                    "page": page_num,
                    "text": text.strip(),
                    "char_count": len(text.strip())
                })
                
                if page_num % 10 == 0:
                    print(f"  Processed page {page_num}/{len(pdf.pages)}")
    
    # Save extracted text
    output = {
        "source": "IRDAI Master Circular on Protection of Policyholders' Interests, 2024",
        "date": "5 September 2024",
        "reference": "IRDAI/PP&GR/CIR/MISC/117/9/2024",
        "total_pages": len(pages_data),
        "total_chars": sum(p["char_count"] for p in pages_data),
        "pages": pages_data
    }
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Extracted {len(pages_data)} pages")
    print(f"   Total characters: {output['total_chars']:,}")
    print(f"   Saved to: {output_path}")
    
    return output

if __name__ == "__main__":
    pdf_path = "data/raw/irdai_master_circular_2024.pdf"
    output_path = "data/reference/irdai_master_circular_extracted.json"
    
    extract_irdai_text(pdf_path, output_path)