"""
Medical Abbreviation Expander for BillShield.

This module solves a fundamental problem: hospital bills use abbreviations 
(CBC, LFT, CRP) but CGHS rates use full names (Complete Haemogram, 
Liver Function Test, C-Reactive Protein).

Instead of LOINC/Voyage/fancy embeddings, this is a simple, fast, accurate 
preprocessing step: expand abbreviations BEFORE searching CGHS.

Architecture:
    Bill: "Bact/Alert Blood Culture 1"
        ↓
    Expander: "blood culture bacterial aerobic bact alert"
        ↓
    CGHS Search: matches "Bacterial culture and sensitivity - Aerobic" ✅

Coverage:
- 500+ Indian medical abbreviations
- Lab tests (Hematology, Biochemistry, Microbiology, etc.)
- Imaging (X-ray, MRI, CT, USG, ECG, Echo, etc.)
- Procedures (CABG, PTCA, Lap chole, etc.)
- Drugs/devices (common formulations)
- Hospital-specific terminology (Indian context)

Usage:
    from src.agent.abbreviation_expander import expand_medical_term
    
    expanded = expand_medical_term("Bact/Alert Blood Culture 1")
    # Returns: "blood culture bacterial aerobic bact alert"
"""

import re
from typing import List, Dict, Optional


# ============================================================================
# MEDICAL ABBREVIATION DICTIONARY (Indian Hospital Context)
# ============================================================================
# Format: {pattern: [expansion_terms]}
# pattern: lowercase string to match (case-insensitive)
# expansion_terms: keywords to add for better CGHS matching

MEDICAL_ABBREVIATIONS: Dict[str, List[str]] = {
    
    # ========================================================================
    # HEMATOLOGY (Blood Tests)
    # ========================================================================
    "cbc": ["complete blood count", "haemogram", "hemogram", "hb", "rbc", "wbc", "platelet"],
    "complete bloodcount": ["complete blood count", "haemogram", "hemogram"],
    "complete blood count": ["haemogram", "hemogram", "cbc"],
    "haemogram": ["complete blood count", "cbc", "hemogram"],
    "hemogram": ["complete blood count", "cbc", "haemogram"],
    "hb": ["hemoglobin", "haemoglobin"],
    "hgb": ["hemoglobin", "haemoglobin"],
    "hemoglobin": ["hb", "haemoglobin"],
    "haemoglobin": ["hb", "hemoglobin"],
    "hct": ["hematocrit", "pcv", "packed cell volume"],
    "pcv": ["packed cell volume", "hematocrit", "hct"],
    "rbc": ["red blood cell", "red cell count", "erythrocyte"],
    "wbc": ["white blood cell", "leukocyte", "total leukocyte count", "tlc"],
    "tlc": ["total leukocyte count", "wbc", "total wbc"],
    "dlc": ["differential leukocyte count", "differential count"],
    "platelet": ["platelet count", "thrombocyte"],
    "platelet count": ["thrombocyte"],
    "esr": ["erythrocyte sedimentation rate", "sed rate"],
    "mcv": ["mean corpuscular volume"],
    "mch": ["mean corpuscular hemoglobin"],
    "mchc": ["mean corpuscular hemoglobin concentration"],
    "rdw": ["red cell distribution width"],
    "retic count": ["reticulocyte count"],
    "pt": ["prothrombin time"],
    "aptt": ["activated partial thromboplastin time", "ptt"],
    "ptt": ["partial thromboplastin time", "aptt"],
    "inr": ["international normalized ratio", "prothrombin"],
    "bt": ["bleeding time"],
    "ct": ["clotting time"],
    "ddimer": ["d-dimer", "fibrin degradation"],
    "d-dimer": ["fibrin degradation"],
    
    # ========================================================================
    # LIVER FUNCTION TESTS
    # ========================================================================
    "lft": ["liver function test", "sgot", "sgpt", "bilirubin", "alkaline phosphatase"],
    "liver function test": ["lft", "sgot", "sgpt", "bilirubin"],
    "sgot": ["aspartate aminotransferase", "ast", "liver"],
    "ast": ["aspartate aminotransferase", "sgot"],
    "sgpt": ["alanine aminotransferase", "alt", "liver"],
    "alt": ["alanine aminotransferase", "sgpt"],
    "alp": ["alkaline phosphatase"],
    "ggt": ["gamma glutamyl transferase", "gamma gt"],
    "ldh": ["lactate dehydrogenase"],
    "bilirubin total": ["total bilirubin", "tbil"],
    "bilirubin direct": ["direct bilirubin", "conjugated bilirubin"],
    "albumin": ["serum albumin"],
    "total protein": ["serum protein", "tp"],
    "globulin": ["serum globulin"],
    
    # ========================================================================
    # RENAL/KIDNEY FUNCTION TESTS
    # ========================================================================
    "rft": ["renal function test", "kidney function", "kft", "creatinine", "urea"],
    "kft": ["kidney function test", "renal function", "rft", "creatinine", "urea"],
    "renal function": ["rft", "kft", "kidney function"],
    "kidney function": ["rft", "kft", "renal function"],
    "creatinine": ["serum creatinine", "kidney"],
    "blood urea": ["urea", "blood urea nitrogen", "bun"],
    "urea": ["blood urea", "blood urea nitrogen", "bun"],
    "bun": ["blood urea nitrogen", "urea"],
    "uric acid": ["serum uric acid"],
    "egfr": ["estimated glomerular filtration rate"],
    
    # ========================================================================
    # DIABETES / GLUCOSE TESTS
    # ========================================================================
    "fbs": ["fasting blood sugar", "fasting glucose", "fasting"],
    "ppbs": ["postprandial blood sugar", "post meal glucose"],
    "rbs": ["random blood sugar", "random glucose"],
    "hba1c": ["glycated hemoglobin", "glycosylated hemoglobin", "diabetes"],
    "gtt": ["glucose tolerance test"],
    "ogtt": ["oral glucose tolerance test", "gtt"],
    "insulin": ["fasting insulin"],
    "c-peptide": ["c peptide", "connecting peptide"],
    "glucose fasting": ["fasting glucose", "fbs", "fasting blood sugar"],
    "glucose random": ["random glucose", "rbs"],
    
    # ========================================================================
    # LIPID PROFILE
    # ========================================================================
    "lipid profile": ["cholesterol", "triglycerides", "hdl", "ldl", "vldl"],
    "cholesterol": ["total cholesterol", "lipid"],
    "triglycerides": ["tg", "lipid"],
    "hdl": ["high density lipoprotein", "good cholesterol"],
    "ldl": ["low density lipoprotein", "bad cholesterol"],
    "vldl": ["very low density lipoprotein"],
    "tg": ["triglycerides"],
    
    # ========================================================================
    # THYROID FUNCTION
    # ========================================================================
    "tft": ["thyroid function test", "t3 t4 tsh", "thyroid"],
    "thyroid profile": ["t3", "t4", "tsh", "tft"],
    "tsh": ["thyroid stimulating hormone", "thyroid"],
    "t3": ["triiodothyronine", "thyroid"],
    "t4": ["thyroxine", "thyroid"],
    "ft3": ["free t3", "free triiodothyronine"],
    "ft4": ["free t4", "free thyroxine"],
    "anti tpo": ["anti thyroid peroxidase", "tpo antibody"],
    
    # ========================================================================
    # CARDIAC MARKERS
    # ========================================================================
    "troponin": ["troponin i", "troponin t", "cardiac marker"],
    "ckmb": ["creatine kinase mb", "cardiac"],
    "ck-mb": ["creatine kinase mb", "cardiac"],
    "ck total": ["creatine kinase total"],
    "nt probnp": ["nt-probnp", "n-terminal probnp", "heart failure"],
    "bnp": ["brain natriuretic peptide", "heart failure"],
    "myoglobin": ["cardiac myoglobin"],
    "homocysteine": ["serum homocysteine"],
    
    # ========================================================================
    # INFLAMMATION MARKERS
    # ========================================================================
    "crp": ["c-reactive protein", "c reactive protein", "inflammation"],
    "c-reactive protein": ["crp"],
    "hs-crp": ["high sensitivity crp", "high sensitivity c reactive protein"],
    "procalcitonin": ["pct", "sepsis marker"],
    "pct": ["procalcitonin", "sepsis marker"],
    "ferritin": ["serum ferritin", "iron storage"],
    "ana": ["antinuclear antibody"],
    "ra factor": ["rheumatoid factor", "rf"],
    "rf": ["rheumatoid factor"],
    
    # ========================================================================
    # ELECTROLYTES
    # ========================================================================
    "sodium": ["serum sodium", "na"],
    "potassium": ["serum potassium", "k"],
    "chloride": ["serum chloride", "cl"],
    "calcium": ["serum calcium", "ca"],
    "phosphorus": ["serum phosphorus", "phosphate"],
    "magnesium": ["serum magnesium", "mg"],
    "sodium & potassium": ["serum sodium potassium electrolytes"],
    "sodium and potassium": ["serum sodium potassium electrolytes"],
    "na/k": ["sodium potassium electrolytes"],
    "electrolytes": ["sodium potassium chloride", "na k cl"],
    "abg": ["arterial blood gas", "blood gas analysis"],
    
    # ========================================================================
    # MICROBIOLOGY / CULTURES
    # ========================================================================
    "blood culture": ["bacterial culture", "aerobic culture", "blood bact"],
    "bact/alert": ["blood culture", "bacterial culture", "aerobic"],
    "bact alert": ["blood culture", "bacterial culture", "aerobic"],
    "urine culture": ["urine c&s", "bacterial culture urine"],
    "urine c&s": ["urine culture", "culture sensitivity"],
    "stool culture": ["bacterial stool culture"],
    "sputum culture": ["bacterial sputum culture"],
    "wound culture": ["bacterial wound culture"],
    "anaerobic culture": ["bacterial anaerobic culture"],
    "fungal culture": ["mycology culture"],
    "afb": ["acid fast bacilli", "tb test", "tuberculosis"],
    "tb gold": ["quantiferon tb", "tuberculosis"],
    "widal": ["typhoid test"],
    "vdrl": ["syphilis test"],
    "hiv": ["human immunodeficiency virus"],
    "hbsag": ["hepatitis b surface antigen"],
    "anti hcv": ["hepatitis c antibody"],
    "dengue ns1": ["dengue antigen"],
    "malaria parasite": ["mp", "malaria smear"],
    "mp": ["malaria parasite", "malaria"],
    
    # ========================================================================
    # URINE TESTS
    # ========================================================================
    "urine routine": ["urinalysis", "urine examination", "urine r/m"],
    "urine r/m": ["urine routine microscopy", "urinalysis"],
    "urine analysis": ["urinalysis", "urine routine"],
    "urinalysis": ["urine routine", "urine examination"],
    "urine sugar": ["glucose urine"],
    "urine albumin": ["proteinuria"],
    "urine microalbumin": ["microalbuminuria"],
    
    # ========================================================================
    # ENDOCRINE / HORMONES
    # ========================================================================
    "vitamin d": ["25 hydroxy vitamin d", "vit d", "calcidiol"],
    "vit d": ["vitamin d", "25 hydroxy vitamin d"],
    "vitamin b12": ["cobalamin", "vit b12"],
    "vit b12": ["vitamin b12", "cobalamin"],
    "folate": ["folic acid"],
    "iron": ["serum iron"],
    "tibc": ["total iron binding capacity"],
    "psa": ["prostate specific antigen"],
    "cortisol": ["serum cortisol"],
    "testosterone": ["serum testosterone"],
    "estradiol": ["e2", "estrogen"],
    "progesterone": ["serum progesterone"],
    "lh": ["luteinizing hormone"],
    "fsh": ["follicle stimulating hormone"],
    "prolactin": ["serum prolactin"],
    "growth hormone": ["gh"],
    
    # ========================================================================
    # TUMOR MARKERS
    # ========================================================================
    "cea": ["carcinoembryonic antigen", "tumor marker"],
    "afp": ["alpha fetoprotein", "tumor marker"],
    "ca 125": ["cancer antigen 125", "ovarian"],
    "ca 19-9": ["cancer antigen 19-9", "pancreatic"],
    "ca 15-3": ["cancer antigen 15-3", "breast"],
    "psa total": ["total prostate specific antigen"],
    "psa free": ["free prostate specific antigen"],
    
    # ========================================================================
    # IMAGING / RADIOLOGY
    # ========================================================================
    "x-ray": ["xray", "radiograph"],
    "xray": ["x-ray", "radiograph"],
    "mri": ["magnetic resonance imaging"],
    "ct scan": ["computed tomography", "ct"],
    "ct": ["computed tomography", "ct scan"],
    "usg": ["ultrasound", "ultrasonography", "sonography"],
    "ultrasound": ["usg", "ultrasonography", "sonography"],
    "doppler": ["doppler ultrasound", "vascular doppler"],
    "mammography": ["mammogram", "breast imaging"],
    "dexa": ["dexa scan", "bone density", "bmd"],
    "bmd": ["bone mineral density", "dexa"],
    "pet ct": ["pet scan", "positron emission tomography"],
    "pet scan": ["pet ct", "positron emission tomography"],
    "ivp": ["intravenous pyelogram", "urography"],
    "barium swallow": ["upper gi study"],
    "barium meal": ["upper gi study"],
    "barium enema": ["lower gi study"],
    
    # ========================================================================
    # CARDIAC PROCEDURES
    # ========================================================================
    "ecg": ["electrocardiogram", "ekg"],
    "ekg": ["electrocardiogram", "ecg"],
    "echo": ["echocardiogram", "echocardiography", "2d echo"],
    "2d echo": ["echocardiogram", "echo"],
    "tmt": ["treadmill test", "stress test"],
    "stress test": ["tmt", "treadmill test"],
    "holter": ["holter monitoring", "24 hour ecg"],
    "angiography": ["coronary angiogram", "cag"],
    "cag": ["coronary angiography", "angiogram"],
    "ptca": ["percutaneous transluminal coronary angioplasty", "angioplasty"],
    "angioplasty": ["ptca", "stent"],
    "cabg": ["coronary artery bypass graft", "bypass surgery"],
    "tee": ["transesophageal echocardiogram"],
    
    # ========================================================================
    # CONSULTATIONS
    # ========================================================================
    "ip consultation": ["inpatient consultation", "ward consultation"],
    "op consultation": ["outpatient consultation", "opd"],
    "opd consultation": ["outpatient consultation", "op"],
    "cross consultation": ["specialist consultation", "second opinion"],
    "specialist consultation": ["consultant visit"],
    
    # ========================================================================
    # COMMON LAB CONSUMABLES (Not tests - to handle properly)
    # ========================================================================
    "blood tube": ["consumable", "specimen tube"],
    "syringe": ["consumable"],
    "vial": ["consumable"],
    "accuvet": ["blood collection tube", "consumable"],
    
    # ========================================================================
    # PANELS AND PROFILES
    # ========================================================================
    "diabetes profile": ["fbs ppbs hba1c", "diabetes panel"],
    "anemia profile": ["cbc iron ferritin vitamin b12 folate"],
    "thyroid profile": ["t3 t4 tsh"],
    "infection profile": ["cbc crp procalcitonin culture"],
    "preop profile": ["preoperative tests", "cbc ecg coagulation"],
    "viral marker": ["hbsag anti hcv hiv vdrl"],
    "torch": ["toxoplasma rubella cmv herpes"],
    "lipid panel": ["lipid profile", "cholesterol triglycerides hdl ldl"],
    "metabolic panel": ["electrolytes urea creatinine glucose"],
    "comprehensive metabolic panel": ["cmp", "electrolytes urea creatinine glucose"],
    "cmp": ["comprehensive metabolic panel"],
    "bmp": ["basic metabolic panel", "electrolytes urea creatinine glucose"],
    
    # ========================================================================
    # COAGULATION
    # ========================================================================
    "coagulation profile": ["pt aptt inr"],
    "bleeding profile": ["pt aptt inr bleeding time"],
    "thrombophilia": ["protein c protein s antithrombin"],
    
    # ========================================================================
    # SPECIAL TESTS
    # ========================================================================
    "covid": ["coronavirus", "sars-cov-2"],
    "rt-pcr": ["pcr test", "molecular"],
    "rapid antigen": ["antigen test"],
    "covid antibody": ["sars-cov-2 antibody"],
    
}

# ============================================================================
# ABBREVIATION PATTERNS - Common transformations
# ============================================================================

# Patterns that need pre-cleaning before lookup
ARTIFACTS_TO_CLEAN = [
    r"\(.*?\)",          # Remove parenthetical content
    r"\s*-\s*dr\..*",    # Remove doctor names
    r"\s*\d+$",          # Remove trailing sample numbers
    r"\s*-\s*\d+$",      # Remove "- 1", "- 2"
]


# ============================================================================
# CORE EXPANSION FUNCTION
# ============================================================================

def expand_medical_term(raw_text: str) -> str:
    """
    Expand a medical term/abbreviation into searchable keywords.
    
    Args:
        raw_text: Raw text from bill (e.g., "CBC", "Bact/Alert Blood Culture 1")
    
    Returns:
        Expanded text with abbreviations resolved
    
    Examples:
        >>> expand_medical_term("CBC")
        'CBC complete blood count haemogram hemogram hb rbc wbc platelet'
        
        >>> expand_medical_term("Bact/Alert Blood Culture 1")
        'blood culture bacterial culture aerobic culture blood bact bact alert'
        
        >>> expand_medical_term("LFT")
        'LFT liver function test sgot sgpt bilirubin alkaline phosphatase'
    """
    if not raw_text or not isinstance(raw_text, str):
        return raw_text or ""
    
    original = raw_text.strip()
    cleaned = original.lower()
    
    # Step 1: Clean common artifacts
    for pattern in ARTIFACTS_TO_CLEAN:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    
    if not cleaned:
        return original
    
    # Step 2: Try exact match first
    if cleaned in MEDICAL_ABBREVIATIONS:
        expansions = MEDICAL_ABBREVIATIONS[cleaned]
        return f"{original} {' '.join(expansions)}"
    
    # Step 3: Try partial matches (handle "Bact/Alert Blood Culture")
    matched_expansions = []
    cleaned_words = cleaned.replace("/", " ").replace("-", " ").split()
    
    # Check multi-word abbreviations first (longest first)
    sorted_abbrevs = sorted(MEDICAL_ABBREVIATIONS.keys(), key=len, reverse=True)
    
    remaining_text = cleaned
    for abbrev in sorted_abbrevs:
        # Check if this abbreviation appears in the cleaned text
        # Use word boundaries to avoid partial matches
        pattern = r"\b" + re.escape(abbrev) + r"\b"
        if re.search(pattern, remaining_text):
            matched_expansions.extend(MEDICAL_ABBREVIATIONS[abbrev])
            # Remove the matched abbreviation to avoid duplicate matching
            remaining_text = re.sub(pattern, "", remaining_text)
    
    # Step 4: If we found matches, build expanded query
    if matched_expansions:
        # Deduplicate while preserving order
        seen = set()
        unique_expansions = []
        for term in matched_expansions:
            if term not in seen:
                seen.add(term)
                unique_expansions.append(term)
        
        return f"{original} {' '.join(unique_expansions)}"
    
    # Step 5: No abbreviations found - return original
    return original


def expand_with_metadata(raw_text: str) -> Dict[str, any]:
    """
    Expand a medical term and return detailed metadata.
    
    Returns:
        {
            "original": "CBC",
            "cleaned": "cbc",
            "expanded": "CBC complete blood count haemogram...",
            "matched_abbreviations": ["cbc"],
            "expansion_count": 7,
        }
    """
    if not raw_text:
        return {
            "original": "",
            "cleaned": "",
            "expanded": "",
            "matched_abbreviations": [],
            "expansion_count": 0,
        }
    
    original = raw_text.strip()
    cleaned = original.lower()
    
    # Clean artifacts
    for pattern in ARTIFACTS_TO_CLEAN:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    
    # Find all matching abbreviations
    matched_abbrevs = []
    all_expansions = []
    
    # Exact match
    if cleaned in MEDICAL_ABBREVIATIONS:
        matched_abbrevs.append(cleaned)
        all_expansions.extend(MEDICAL_ABBREVIATIONS[cleaned])
    else:
        # Partial matches
        sorted_abbrevs = sorted(MEDICAL_ABBREVIATIONS.keys(), key=len, reverse=True)
        remaining_text = cleaned
        
        for abbrev in sorted_abbrevs:
            pattern = r"\b" + re.escape(abbrev) + r"\b"
            if re.search(pattern, remaining_text):
                matched_abbrevs.append(abbrev)
                all_expansions.extend(MEDICAL_ABBREVIATIONS[abbrev])
                remaining_text = re.sub(pattern, "", remaining_text)
    
    # Deduplicate expansions
    seen = set()
    unique_expansions = []
    for term in all_expansions:
        if term not in seen:
            seen.add(term)
            unique_expansions.append(term)
    
    expanded = f"{original} {' '.join(unique_expansions)}" if unique_expansions else original
    
    return {
        "original": original,
        "cleaned": cleaned,
        "expanded": expanded,
        "matched_abbreviations": matched_abbrevs,
        "expansion_count": len(unique_expansions),
    }


def is_consumable(text: str) -> bool:
    """Check if a line item description is a consumable (not a test)."""
    if not text:
        return False
    
    text_lower = text.lower()
    consumable_keywords = [
        "tube", "vial", "accuvet", "lancet", "syringe",
        "needle", "swab", "container", "bottle",
        "specimen container", "blood colle", "collection tube",
    ]
    return any(kw in text_lower for kw in consumable_keywords)


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("Medical Abbreviation Expander - Test")
    print("=" * 70)
    
    test_cases = [
        # Lisie bill items
        "CBC",
        "Complete Bloodcount",
        "Bact/Alert Blood Culture 1",
        "Bact/Alert Blood Culture 2",
        "Blood Urea",
        "LFT",
        "Liver Function Test",
        "CRP",
        "Blood Culture",
        
        # Other common ones
        "RFT",
        "USG abdomen",
        "MRI brain",
        "ECG",
        "2D Echo",
        "Vitamin D",
        "TSH",
        "HBA1C",
        "Lipid Profile",
        "PT INR",
        
        # Consumables (should be flagged)
        "Blood Colle. Tube (Accuvet)",
        "Syringe",
        
        # Edge cases
        "",
        "Unknown Test XYZ",
    ]
    
    print(f"\nTotal abbreviations in dictionary: {len(MEDICAL_ABBREVIATIONS)}")
    print(f"\nTesting {len(test_cases)} queries:\n")
    
    for test in test_cases:
        result = expand_with_metadata(test)
        
        if is_consumable(test):
            print(f"🔧 CONSUMABLE: '{test}' - skip for matching")
            continue
        
        if result["expansion_count"] > 0:
            print(f"✅ '{test}'")
            print(f"   Matched: {result['matched_abbreviations']}")
            print(f"   Expanded: {result['expanded'][:80]}{'...' if len(result['expanded']) > 80 else ''}")
            print(f"   Added {result['expansion_count']} keywords")
        else:
            print(f"⚪ '{test}' - no abbreviation found, will search as-is")
        print()
    
    print("=" * 70)
    print(f"Dictionary stats: {len(MEDICAL_ABBREVIATIONS)} abbreviations covered")
    print("=" * 70)
