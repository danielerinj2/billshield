"""
Document Type Classifier
Detects whether an uploaded document is a hospital bill, pharmacy invoice, lab report, etc.
"""

from typing import Dict, List


class DocumentType:
    """Document type constants"""
    HOSPITAL_BILL = "hospital_bill"
    PHARMACY_BILL = "pharmacy_bill"
    LAB_BILL = "lab_bill"
    DEVICE_INVOICE = "device_invoice"
    INSURANCE_DOCUMENT = "insurance_document"
    UNKNOWN = "unknown"


# Detection patterns
HOSPITAL_SIGNALS = [
    "room charges", "bed charges", "ward", "icu", "ccu", "nicu",
    "operation", "ot charges", "anesthet", "anaesthet",
    "consultation", "department", "admission", "discharge",
    "patient liability", "nursing charges", "deluxe ward",
    "obs & gyne", "obs & gynecology", "cardiology", "ortho"
]

PHARMACY_SIGNALS = [
    "bill of supply", "batch no", "batch", "expiry", "mrp",
    "pkg", "medical store", "pharmacy", "tab", "cap", "inj", "syrup",
    "gross amt", "discount", "net amt", "composition",
    "drug", "medicine", "capsule", "tablet", "injection"
]

LAB_SIGNALS = [
    "test report", "sample", "specimen", "lab", "diagnostic",
    "pathology", "radiology", "imaging",
    "cbc", "lft", "kft", "rft", "lipid profile",
    "mri", "ct scan", "x-ray", "xray", "ultrasound", "usg",
    "blood test", "urine test", "biopsy",
    "laboratory", "laboratory report", "mg/dl", "miu/ml", "g%",
    "hemoglobin", "haemoglobin", "glucose", "protein", "bilirubin",
    "creatinine", "tsh", "thyroid", "cholesterol", "triglyceride",
    "platelet", "rbc", "wbc", "leukocyte", "leucocyte",
    "erythrocyte", "ketone", "urobilinogen", "neutrophil",
    "lymphocyte", "monocyte", "eosinophil", "basophil",
    "sgpt", "sgot", "alt", "ast", "ggt", "alkaline phosphatase",
    "albumin", "globulin", "prothrombin", "inr",
    "beta hcg", "hcg", "hbs ag", "hiv", "vdrl", "crp", "esr",
    "biological ref", "reference range", "neuberg", "thyrocare",
    "metropolis", "srl", "dr lal", "pathlab"
]

DEVICE_SIGNALS = [
    "stent", "implant", "pacemaker", "catheter", "valve",
    "prosthesis", "mesh", "manufacturer", "device code",
    "model no", "lot no", "serial no", "des", "drug eluting"
]

INSURANCE_SIGNALS = [
    "claim", "policy no", "policy number", "tpa",
    "settlement", "intimation", "pre-authorization",
    "rejected", "approved amount", "deductible", "co-pay",
    "insurer", "insurance company", "claim no"
]


def classify_document(parsed_data: Dict) -> str:
    """
    Classify a parsed document into a document type.
    
    Args:
        parsed_data: Parsed bill data with line_items, metadata, etc.
        
    Returns:
        One of DocumentType constants
    """
    line_items = parsed_data.get("line_items", [])
    
    # NEW: Detect category summary bills (not itemized)
    if _is_category_summary(line_items):
        print("📋 Detected category summary bill - routing to HOSPITAL_BILL analyzer")
        return DocumentType.HOSPITAL_BILL  # Don't route to PharmacyAnalyzer
    
    # Extract text content for pattern matching
    text_content = _extract_text_content(parsed_data)
    text_lower = text_content.lower()
    
    # Count signal matches
    hospital_score = _count_signals(text_lower, HOSPITAL_SIGNALS)
    pharmacy_score = _count_signals(text_lower, PHARMACY_SIGNALS)
    lab_score = _count_signals(text_lower, LAB_SIGNALS)
    device_score = _count_signals(text_lower, DEVICE_SIGNALS)
    insurance_score = _count_signals(text_lower, INSURANCE_SIGNALS)
    
    # Check line items for pharmacy/lab patterns
    pharmacy_item_ratio = _pharmacy_item_ratio(line_items) if line_items else 0
    lab_item_ratio = _lab_item_ratio(line_items) if line_items else 0
    
    print(f"🔍 Classification scores: Hospital={hospital_score}, Pharmacy={pharmacy_score} (items={pharmacy_item_ratio:.0%}), Lab={lab_score} (items={lab_item_ratio:.0%}), Device={device_score}, Insurance={insurance_score}")
    
    # Decision logic (order matters)
    
    # Insurance document (distinct patterns)
    if insurance_score >= 3:
        return DocumentType.INSURANCE_DOCUMENT
    
    # Pharmacy bill (high item ratio OR strong signals)
    if pharmacy_item_ratio >= 0.6 or (pharmacy_score >= 5 and pharmacy_item_ratio >= 0.4):
        return DocumentType.PHARMACY_BILL
    
    # Lab bill (high item ratio OR strong signals)
    if lab_item_ratio >= 0.6 or (lab_score >= 5 and lab_item_ratio >= 0.4):
        return DocumentType.LAB_BILL
    
    # Device invoice (specific keywords)
    if device_score >= 3:
        return DocumentType.DEVICE_INVOICE
    
    # Hospital bill (default for medical bills with room/operation charges)
    if hospital_score >= 4:
        return DocumentType.HOSPITAL_BILL
    
    # Mixed or unclear - check if predominantly one type
    if pharmacy_score > hospital_score and pharmacy_score >= 3:
        return DocumentType.PHARMACY_BILL
    
    if lab_score > hospital_score and lab_score >= 3:
        return DocumentType.LAB_BILL
    
    # Default: treat as hospital bill if it has basic billing structure
    if hospital_score >= 2 or (line_items and len(line_items) >= 3):
        return DocumentType.HOSPITAL_BILL
    
    return DocumentType.UNKNOWN


def _is_category_summary(line_items: List[Dict]) -> bool:
    """
    Detect if this is a category-summary bill (not itemized).
    
    Category summary bills have lines like:
    - MEDICINE CHARGES: ₹18,826
    - ROOM/WARD RENT: ₹3,700
    - LABORATORY: ₹4,460
    
    NOT individual items like:
    - Paracetamol 500mg Tab (Batch: XYZ123, MRP: ₹2.50)
    - Complete Blood Count (CBC)
    """
    if not line_items or len(line_items) < 3:
        return False
    
    category_keywords = [
        "medicine charges", "pharmacy charges", "drug charges",
        "room/ward rent", "room charges", "bed charges", "ward rent",
        "laboratory", "laboratory charges", "lab charges",
        "consultation", "consultation charges", "ip consultation",
        "procedures", "procedure charges", "surgical charges",
        "medical equipment", "equipment charges",
        "nursing charges", "nursing procedure",
        "hospital services", "service charges",
        "ot charges", "operation theatre",
        "diet charge", "diet charges"
    ]
    
    summary_count = 0
    for item in line_items[:10]:  # Check first 10 items
        desc = item.get("description", "").lower().strip()
        
        # Check if description is a category name (not a specific item)
        if any(kw == desc or desc.startswith(kw) for kw in category_keywords):
            summary_count += 1
    
    # If 3+ items are category names (not specific drugs/tests), it's a summary
    return summary_count >= 3


def _extract_text_content(parsed_data: Dict) -> str:
    """Extract all text content from parsed data for pattern matching."""
    parts = []
    
    # Metadata
    for key in ["hospital_name", "department", "diagnosis", "procedure_name", "bill_number"]:
        val = parsed_data.get(key)
        if val:
            parts.append(str(val))
    
    # Line items
    for item in parsed_data.get("line_items", []):
        parts.append(item.get("description", ""))
        parts.append(item.get("original_text", ""))
        parts.append(item.get("category", ""))
    
    return " ".join(parts)


def _count_signals(text: str, signals: List[str]) -> int:
    """Count how many signal patterns appear in text."""
    return sum(1 for signal in signals if signal in text)


def _pharmacy_item_ratio(line_items: List[Dict]) -> float:
    """Calculate what ratio of line items look like pharmacy products."""
    if not line_items:
        return 0.0
    
    pharmacy_keywords = ["tab", "cap", "inj", "syrup", "injection", "capsule", "tablet", "ml", "mg"]
    
    pharmacy_count = sum(
        1 for item in line_items
        if any(kw in item.get("description", "").lower() for kw in pharmacy_keywords)
    )
    
    return pharmacy_count / len(line_items)


def _lab_item_ratio(line_items: List[Dict]) -> float:
    """Calculate what ratio of line items look like lab tests."""
    if not line_items:
        return 0.0
    
    lab_keywords = [
        "test", "scan", "ray", "mri", "ct", "ultrasound", "usg",
        "cbc", "lft", "kft", "rft", "blood", "urine", "culture",
        "biopsy", "pathology", "specimen", "sample",
        # Common lab test names (added for better classification)
        "hemoglobin", "glucose", "protein", "bilirubin", "creatinine",
        "sgpt", "sgot", "alkaline", "ast", "alt", "ggt",
        "tsh", "thyroid", "lipid", "cholesterol", "triglyceride",
        "sodium", "potassium", "calcium", "phosphate", "magnesium",
        "platelet", "rbc", "wbc", "haemoglobin", "hematology",
        "cardiac", "troponin", "crp", "esr", "vdrl", "hiv",
        "albumin", "globulin", "prothrombin", "clotting",
        "urinalysis", "urine examination", "ketone", "leucocyte",
        "epithelial", "bacteria", "cast", "crystal", "eosinophil",
        "neutrophil", "lymphocyte", "monocyte", "basophil"
    ]
    
    lab_count = sum(
        1 for item in line_items
        if any(kw in item.get("description", "").lower() for kw in lab_keywords)
    )
    
    return lab_count / len(line_items)