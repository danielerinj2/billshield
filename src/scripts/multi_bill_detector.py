"""Detect multi-bill PDFs before parsing."""
import pdfplumber


def detect_multi_bill(pdf_path: str) -> dict:
    """
    Detect if PDF contains multiple separate bills.
    
    Returns:
        {
            "is_multi": bool,
            "page_count": int,
            "distinct_bills": int
        }
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)
            
            # Single page = definitely single bill
            if page_count == 1:
                return {
                    "is_multi": False,
                    "page_count": 1,
                    "distinct_bills": 1
                }
            
            # Count pages with bill/invoice headers
            bill_indicators = [
                "BILL NO", "INVOICE NO", "RECEIPT NO", "BILL CUM RECEIPT",
                "BILL NUMBER", "INVOICE NUMBER", "RECEIPT NUMBER"
            ]
            
            bill_page_count = 0
            for page in pdf.pages:
                text = (page.extract_text() or "").upper()
                if any(indicator in text for indicator in bill_indicators):
                    bill_page_count += 1
            
            # If 2+ pages have bill headers, it's multi-bill
            is_multi = bill_page_count > 1
            
            return {
                "is_multi": is_multi,
                "page_count": page_count,
                "distinct_bills": bill_page_count if is_multi else 1
            }
            
    except Exception as e:
        print(f"⚠️ Multi-bill detection failed: {e}")
        # On error, assume single bill (safer to process than reject)
        return {
            "is_multi": False,
            "page_count": 1,
            "distinct_bills": 1
        }
