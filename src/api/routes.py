"""FastAPI routes for BillShield."""

import json
import os
import tempfile
from src.scripts.multi_bill_detector import detect_multi_bill
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from supabase import Client

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.enums import TA_LEFT
from fastapi.responses import StreamingResponse
from io import BytesIO

from src.api.database import get_db
from src.api.models import (
    AnalysisCreate,
    AnalysisResult,
    IssueDetail,
    LetterGenerate,
    LetterResponse
)
from src.agent.core import BillShieldAgent
from src.rag.retrieval import BillShieldRAG
from src.letters.generator import AdaptiveLetterGenerator
from src.scripts.parse_bill_pdf import parse_bill_pdf
from src.scripts.parse_discharge_pdf import parse_discharge_pdf
from src.scripts.parse_rejection_pdf import parse_rejection_pdf
from src.scripts.vision_llm_parser import parse_pdf_with_vision

router = APIRouter()

# Load the RAG system ONCE at import time and reuse it for every analysis.
# Building BillShieldRAG() per-request reloads a ~90MB model each time and
# crashes the 512MB free tier. One shared instance fixes that.
_rag_instance = None

def get_rag():
    """Return a single shared BillShieldRAG, creating it on first use."""
    global _rag_instance
    if _rag_instance is None:
        print("🔧 Loading RAG system (one-time)...")
        _rag_instance = BillShieldRAG()
        print("✅ RAG system loaded and cached")
    return _rag_instance

import re
from datetime import datetime, timedelta

def redact_pii(text: str) -> str:
    """Redact Aadhaar, PAN, and other PII from logs."""
    if not isinstance(text, str):
        text = str(text)
    
    # Redact 12-digit Aadhaar (with or without spaces/dashes)
    text = re.sub(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', 'XXXX-XXXX-XXXX', text)
    
    # Redact PAN (format: ABCDE1234F)
    text = re.sub(r'\b[A-Z]{5}\d{4}[A-Z]\b', 'XXXXX1234X', text)
    
    # Redact phone numbers (10 digits)
    text = re.sub(r'\b[6-9]\d{9}\b', 'XXXXXXXXXX', text)
    
    # Redact email addresses
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', 'user@redacted.com', text)
    
    return text

def filter_prompt_injection(text: str) -> str:
    """Remove prompt injection attempts from bill text."""
    if not isinstance(text, str):
        return text
    
    # Patterns that indicate prompt injection
    injection_patterns = [
        r'ignore\s+(all\s+)?(previous\s+)?(instructions|prompts|rules)',
        r'disregard\s+(all\s+)?(previous\s+)?(instructions|prompts|rules)',
        r'override\s+system',
        r'system\s*:\s*',
        r'assistant\s*:\s*',
        r'you\s+are\s+now',
        r'forget\s+(everything|all)',
        r'new\s+instructions',
        r'admin\s+mode',
        r'developer\s+mode',
        r'sudo\s+mode',
    ]
    
    cleaned = text
    for pattern in injection_patterns:
        cleaned = re.sub(pattern, '[FILTERED]', cleaned, flags=re.IGNORECASE)
    
    return cleaned

# ============================================================
# SCENARIO CLASSIFICATION + LETTER VALIDATION
# ============================================================

def classify_scenario(analysis_data: dict, user_input) -> str:
    """Classify which letter set applies to this bill.
    
    Returns one of:
        A_cash_clarification: No insurance, low-confidence issues only
        B_cash_objection: No insurance, confirmed overcharges
        C_insurance_dispute: Insurance involved, claim issues
        D_hospital_overcharge_only: Insurance involved, only hospital overcharges
    """
    # Detect insurance involvement
    has_policy = bool(getattr(user_input, 'policy_number', None) and str(user_input.policy_number).strip())
    has_claim = bool(getattr(user_input, 'claim_number', None) and str(user_input.claim_number).strip())
    has_insurer = bool(getattr(user_input, 'insurer_name', None) and str(user_input.insurer_name).strip())
    has_approved = (analysis_data.get('total_approved', 0) or 0) > 0
    has_rejected = (analysis_data.get('total_rejected', 0) or 0) > 0
    
    has_insurance = has_policy or has_claim or has_insurer or has_approved or has_rejected
    
    # Detect overcharges
    verified_overcharge = analysis_data.get('total_verified_overcharge', 0) or 0
    has_confirmed_overcharges = verified_overcharge > 0
    
    high_conf_issues = [
        i for i in analysis_data.get('issues', [])
        if i.get('confidence') == 'high'
    ]
    has_high_confidence_issues = len(high_conf_issues) > 0
    
    has_strong_evidence = has_confirmed_overcharges or has_high_confidence_issues
    
    # Detect claim rejection issues
    rejection_issues = [
        i for i in analysis_data.get('issues', [])
        if i.get('issue_type') in ['rejection_invalid', 'rejection_delayed', 'policy_violation']
    ]
    has_claim_issues = len(rejection_issues) > 0 or has_rejected
    
    # Classify
    if not has_insurance and not has_strong_evidence:
        return "A_cash_clarification"
    elif not has_insurance and has_strong_evidence:
        return "B_cash_objection"
    elif has_insurance and has_claim_issues:
        return "C_insurance_dispute"
    elif has_insurance and has_strong_evidence:
        return "D_hospital_overcharge_only"
    else:
        # Insurance involved but no issues either way — default to clarification
        return "A_cash_clarification"


# Maps scenario -> which letters to generate
LETTER_MATRIX = {
    "A_cash_clarification": ["hospital_clarification", "patient_summary"],
    "B_cash_objection": ["hospital_professional", "patient_summary"],
    "C_insurance_dispute": ["hospital_professional", "insurer", "patient_summary"],
    "D_hospital_overcharge_only": ["hospital_professional", "patient_summary"],
}


def validate_letter_content(content: str, scenario: str, analysis_data: dict) -> tuple:
    """Validate letter doesn't contain contradictions or unfilled placeholders.
    
    Returns (is_valid, reason_if_invalid).
    """
    if not content or len(content.strip()) < 100:
        return False, "Letter content too short"
    
    # Check 1: No unfilled bracket placeholders (case-insensitive)
    bracket_placeholders = [
        '[Hospital Name]', '[Patient Name]', '[Bill Number]',
        '[Policy Number]', '[Claim Number]', '[Insurance Company]',
        '[INSURER NAME]', '[HOSPITAL NAME]'
    ]
    for placeholder in bracket_placeholders:
        if placeholder in content:
            return False, f"Contains unfilled placeholder: {placeholder}"
    
    # Check 2: No encoding artifacts (n0, n63 instead of ₹)
    import re
    if re.search(r'\bn\d{1,7}\b(?!\w)', content):
        return False, "Contains currency encoding artifact (n0, n63, etc.)"
    
    # Check 3: Scenario-specific contradictions
    verified = analysis_data.get('total_verified_overcharge', 0) or 0
    
    if scenario == "A_cash_clarification":
        # Should NOT contain confrontational overcharge language
        forbidden = [
            'overcharges detected',
            'Overcharges Detected',
            'demand refund',
            'demand immediate',
            'IRDAI violations',
            'regulation violations'
        ]
        for word in forbidden:
            if word.lower() in content.lower():
                return False, f"Clarification letter contains confrontational language: '{word}'"
    
    # Check 4: If verified overcharge is 0, no "refund of Rs. 0" language
    if verified == 0:
        if 'Refund of ₹0' in content or 'Refund of Rs. 0' in content or 'refund of rs. 0' in content.lower():
            return False, "Contains 'Refund of Rs. 0' (no overcharges but asking for refund)"
    
    # Check 5: Validate cited regulations exist (basic check)
    # Look for CGHS, NPPA, IRDAI references
    cghs_pattern = r'CGHS\s+(?:rate|code|entry)\s*[:\-]?\s*(\d+[\d\.\-]*)'
    nppa_pattern = r'NPPA\s+(?:ceiling|price|rate)\s*[:\-]?\s*₹?\s*(\d+)'
    irdai_pattern = r'IRDAI\s+(?:guideline|regulation|circular)\s*[:\-]?\s*([A-Z0-9\-/]+)'
    
    cghs_matches = re.findall(cghs_pattern, content, re.IGNORECASE)
    nppa_matches = re.findall(nppa_pattern, content, re.IGNORECASE)
    irdai_matches = re.findall(irdai_pattern, content, re.IGNORECASE)
    
    # Log found references for manual verification
    if cghs_matches or nppa_matches or irdai_matches:
        print(f"🔍 Regulation references found in letter:")
        if cghs_matches:
            print(f"   CGHS codes: {cghs_matches}")
        if nppa_matches:
            print(f"   NPPA prices: {nppa_matches}")
        if irdai_matches:
            print(f"   IRDAI refs: {irdai_matches}")
    
    return True, "OK"


# Supported file types
ALLOWED_MIME_TYPES = [
    'application/pdf',
    'image/jpeg',
    'image/jpg',
    'image/png',
    'image/tiff',
    'image/bmp',
    'image/webp'
]

IMAGE_EXTENSIONS = ['png', 'jpg', 'jpeg', 'tiff', 'tif', 'bmp', 'webp']


@router.post("/analysis/create")
async def create_analysis(
    data: AnalysisCreate,
    db: Client = Depends(get_db),
    request: Request = None
):
    """Create a new analysis record."""
    try:
        # Extract session token from header (sent by frontend)
        session_token = request.headers.get("X-Session-Token") if request else None
        
        # ============================================================
        # GUARDRAIL 3: RATE LIMITING
        # ============================================================
        # Get client IP
        client_ip = request.client.host if request else "unknown"
        
        # Check recent analyses from this IP/session in the last hour
        one_hour_ago = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        
        # Count recent analyses
        recent_count_query = db.table('analyses').select('id', count='exact')
        
        if session_token:
            # For logged-in users: check session_token
            recent = recent_count_query.eq('session_token', session_token).gte('created_at', one_hour_ago).execute()
        else:
            # For anonymous: would need IP tracking table (skip for now, just warn)
            recent = None
        
        # Apply limits
        if recent and recent.count:
            # Anonymous: 3/hour, Logged-in: 20/hour (simple heuristic: if session exists, assume logged in)
            limit = 20 if session_token else 3
            
            if recent.count >= limit:
                raise HTTPException(
                    status_code=429, 
                    detail=f"Rate limit exceeded. Please wait before creating another analysis. Limit: {limit} per hour."
                )
        
        # ============================================================
        # Create analysis record
        # ============================================================
        result = db.table('analyses').insert({
            'status': 'processing',
            'patient_name': data.patient_name,
            'hospital_name': data.hospital_name,
            'bill_number': data.bill_number,
            'policy_number': data.policy_number,
            'claim_number': data.claim_number,
            'session_token': session_token
        }).execute()
        
        analysis_id = result.data[0]['id']
        
        return {
            "analysis_id": analysis_id,
            "status": "created"
        }
    
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"ERROR in create_analysis: {error_details}")
        raise HTTPException(status_code=500, detail=f"Failed to create analysis: {str(e)}")


@router.post("/documents/upload")
async def upload_document(
    analysis_id: str = Form(...),
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    db: Client = Depends(get_db)
):
    """Upload a document (PDF or image) to Supabase Storage."""
    try:
        # Validate file type
        if file.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid file type. Allowed: PDF, JPG, PNG, TIFF, BMP, WEBP"
            )
        
        # Read file
        contents = await file.read()
        
        # Upload to Supabase Storage
        file_path = f"{analysis_id}/{doc_type}_{file.filename}"
        
        storage_result = db.storage.from_('documents').upload(
            path=file_path,
            file=contents,
            file_options={"content-type": file.content_type}
        )
        
        # Record in documents table
        db.table('documents').insert({
            'analysis_id': analysis_id,
            'doc_type': doc_type,
            'file_path': file_path,
            'file_size': len(contents)
        }).execute()
        
        return {
            "file_path": file_path,
            "status": "uploaded"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


def parse_document(temp_file_path: str, doc_type: str, is_image: bool):
    """
    Parse a document using the appropriate parser.
    Falls back to vision LLM for images or when regex fails.
    """
    if doc_type == 'bill':
        if is_image:
            print("📸 Image file - using vision LLM...")
            return parse_pdf_with_vision(temp_file_path, doc_type='bill')
        
        # Try regex parser first for PDFs
        try:
            print("🔍 TIER 1: Attempting regex parser...")
            data = parse_bill_pdf(temp_file_path)
            line_count = len(data.get('line_items', []))
            
            # QUALITY CHECK: Verify we got meaningful data
            has_amounts = any(
                item.get('amount', 0) > 0 
                for item in data.get('line_items', [])
            )
            has_descriptions = any(
                len(item.get('description', '').strip()) > 3
                for item in data.get('line_items', [])
            )

            # NEW: Check for garbage OCR (scanned PDFs)
            line_items = data.get('line_items', [])
            garbage_count = 0
            for item in line_items[:5]:  # Check first 5 items
                desc = item.get('description', '')
                if len(desc) > 0:
                    # Count non-letter characters (excluding spaces)
                    non_letter_count = sum(1 for c in desc if not c.isalpha() and c != ' ')
                    # If >40% of characters are garbage, flag it
                    if non_letter_count / len(desc) > 0.4:
                        garbage_count += 1
                        print(f"⚠️ Garbage detected in: {desc[:50]}")

            if line_count == 0 or not (has_amounts and has_descriptions):
                print(f"⚠️ Regex returned low-quality data (empty)")
                raise ValueError("Regex quality check failed")

            if garbage_count >= 2:  # If 2+ items are garbage
                print(f"⚠️ Regex returned garbage OCR text ({garbage_count}/5 items)")
                raise ValueError("Scanned PDF detected - need vision parser")

            print(f"✅ TIER 1 SUCCESS: Regex parser extracted {line_count} items")
            return data
            
        except Exception as regex_error:
            print(f"⚠️ TIER 1 FAILED: {regex_error}")
            
            # TIER 2: Try standard vision LLM
            try:
                print("🔍 TIER 2: Attempting standard vision LLM...")
                data = parse_pdf_with_vision(temp_file_path, doc_type='bill')
                line_count = len(data.get('line_items', []))
                
                if line_count > 0:
                    print(f"✅ TIER 2 SUCCESS: Vision LLM extracted {line_count} items")
                    return data
                else:
                    raise ValueError("Vision LLM returned 0 items")
                    
            except Exception as vision_error:
                print(f"⚠️ TIER 2 FAILED: {vision_error}")
                
                # TIER 3: Final fallback to Groq
                try:
                    print("🔍 TIER 3: Attempting Groq vision...")
                    from src.scripts.groq_vision_parser import parse_with_groq_vision
                    
                    data = parse_with_groq_vision(temp_file_path, doc_type='bill')
                    line_count = len(data.get('line_items', []))
                    
                    if line_count > 0:
                        print(f"✅ TIER 3 SUCCESS: Groq extracted {line_count} items")
                        return data
                    else:
                        raise ValueError("Groq returned 0 items")
                        
                except Exception as groq_error:
                    print(f"⚠️ TIER 3 FAILED: {groq_error}")
                    raise ValueError("All parsing tiers failed")
    
    elif doc_type == 'discharge':
        if is_image:
            print("📸 Image file - using vision LLM...")
            return parse_pdf_with_vision(temp_file_path, doc_type='discharge')
        
        try:
            data = parse_discharge_pdf(temp_file_path)
            if not data.get('patient_info', {}).get('name'):
                print("⚠️ Regex returned empty data, falling back to vision LLM...")
                return parse_pdf_with_vision(temp_file_path, doc_type='discharge')
            return data
        except Exception as e:
            print(f"⚠️ Regex parser failed: {e}, trying vision LLM...")
            return parse_pdf_with_vision(temp_file_path, doc_type='discharge')
    
    elif doc_type == 'rejection':
        if is_image:
            print("📸 Image file - using vision LLM...")
            return parse_pdf_with_vision(temp_file_path, doc_type='rejection')
        
        try:
            data = parse_rejection_pdf(temp_file_path)
            if not data.get('claim_metadata', {}).get('claim_number'):
                print("⚠️ Regex returned empty data, falling back to vision LLM...")
                return parse_pdf_with_vision(temp_file_path, doc_type='rejection')
            return data
        except Exception as e:
            print(f"⚠️ Regex parser failed: {e}, trying vision LLM...")
            return parse_pdf_with_vision(temp_file_path, doc_type='rejection')
    
    return None


@router.post("/analysis/run/{analysis_id}")
async def run_analysis(
    analysis_id: str,
    background_tasks: BackgroundTasks
):
    """Start analysis in the background and return immediately.
    
    The heavy work (parsing, vision LLM, RAG, agent) runs in _process_analysis
    after this response is sent. The frontend polls GET /analysis/{id} and waits
    for status to flip from 'processing' to 'complete' (or 'failed').
    """
    # Schedule the worker to run after we return
    background_tasks.add_task(_process_analysis, analysis_id)
    
    # Return instantly — connection closes, no timeout possible
    return {
        "analysis_id": analysis_id,
        "status": "processing"
    }


def _process_analysis(analysis_id: str):
    """Background worker: does the actual analysis. Not a route.
    
    Creates its own DB connection via the singleton (safe, since get_db
    returns a shared long-lived client). Updates the analyses row to
    'complete' or 'failed' so the polling frontend knows when it's done.
    """
    db = get_db()  # same singleton client the routes use
    try:
        # Get documents for this analysis
        docs = db.table('documents').select('*').eq('analysis_id', analysis_id).execute()
        
        if not docs.data:
            print(f"❌ No documents found for analysis {analysis_id}")
            db.table('analyses').update({'status': 'failed'}).eq('id', analysis_id).execute()
            return
        
        # Initialize data containers
        bill_data = None
        discharge_data = None
        rejection_data = None
        
        # Create temp directory for downloaded files
        temp_dir = tempfile.mkdtemp()
        print(f"📁 Created temp directory: {temp_dir}")
        
        for doc in docs.data:
            try:
                # Download file from Supabase Storage
                print(f"⬇️ Downloading {doc['doc_type']}: {doc['file_path']}")
                file_bytes = db.storage.from_('documents').download(doc['file_path'])
                
                # Get original file extension
                original_filename = doc['file_path'].split('/')[-1]
                file_extension = original_filename.split('.')[-1].lower()
                
                # Save to temp file with CORRECT extension
                temp_file_path = os.path.join(temp_dir, f"{doc['doc_type']}.{file_extension}")
                with open(temp_file_path, 'wb') as f:
                    f.write(file_bytes)
                
                print(f"💾 Saved to temp: {temp_file_path}")
                
                # Check if it's an image file
                is_image = file_extension in IMAGE_EXTENSIONS
                
                # Parse using the helper function
                print(f"🔍 Parsing {doc['doc_type']} ({file_extension})...")
                parsed_data = parse_document(temp_file_path, doc['doc_type'], is_image)
                
                # GUARDRAIL: Apply prompt injection filter to descriptions
                if parsed_data and 'line_items' in parsed_data:
                    for item in parsed_data['line_items']:
                        if 'description' in item:
                            item['description'] = filter_prompt_injection(item['description'])
                
                # Store parsed data
                if doc['doc_type'] == 'bill':
                    bill_data = parsed_data
                    print(f"✓ Bill parsed: {len(bill_data.get('line_items', []))} items")
                elif doc['doc_type'] == 'discharge':
                    discharge_data = parsed_data
                    print("✓ Discharge parsed")
                elif doc['doc_type'] == 'rejection':
                    rejection_data = parsed_data
                    print("✓ Rejection parsed")
                    
            except Exception as parse_error:
                print(f"❌ Error parsing {doc['doc_type']}: {str(parse_error)}")
                import traceback
                traceback.print_exc()
                # Continue with other docs even if one fails
                continue
        
        # Verify we got at least the bill
        if not bill_data:
            print(f"❌ Could not parse hospital bill for analysis {analysis_id}")
            db.table('analyses').update({'status': 'failed'}).eq('id', analysis_id).execute()
            return
        
        print(f"📋 Documents parsed:")
        print(f"   Bill: {'✓' if bill_data else '✗'}")
        print(f"   Discharge: {'✓' if discharge_data else '✗'}")
        print(f"   Rejection: {'✓' if rejection_data else '✗'}")
        
        print("="*80)
        print("🔍 DEBUG: VISION PARSER OUTPUT")
        print("="*80)
        # GUARDRAIL: Redact PII from debug logs
        print(redact_pii(json.dumps(bill_data, indent=2)))
        print("="*80)
        
        # Initialize RAG (shared singleton) and agent
        rag = get_rag()
        agent = BillShieldAgent(rag_system=rag)
        
        # Run analysis
        result = agent.analyze(
            bill_data=bill_data,
            discharge_data=discharge_data,
            rejection_data=rejection_data,
            policy_available=True
        )
        
        # DEBUG: Log what agent returned
        print(f"🔍 Agent returned type: {type(result)}")
        print(f"🔍 Result has issues attr: {hasattr(result, 'issues')}")
        print(f"🔍 Result.issues type: {type(result.issues) if hasattr(result, 'issues') else 'N/A'}")
        print(f"🔍 Result.issues length: {len(result.issues) if hasattr(result, 'issues') else 0}")
        if hasattr(result, 'issues') and len(result.issues) > 0:
            print(f"🔍 First issue: {result.issues[0]}")
        
        # Update analysis record (only update metadata fields if they were extracted, preserve existing values otherwise)
        update_payload = {
            'status': 'complete',
            'bill_total': result.total_bill,
            'insurance_approved': result.total_approved,
            'insurance_rejected': result.total_rejected,
            'patient_liability': result.total_patient_liability,
            'verified_overcharge': result.total_verified_overcharge,
            'min_recoverable': result.estimated_recoverable['min'],
            'max_recoverable': result.estimated_recoverable['max'],
            'raw_result': result.to_dict()
        }
        
        # Only update metadata if we successfully extracted it (don't overwrite user-entered values with null)
        if result.hospital_name:
            update_payload['hospital_name'] = result.hospital_name
        if result.bill_number:
            update_payload['bill_number'] = result.bill_number
        if result.patient_name:
            update_payload['patient_name'] = result.patient_name
        if result.policy_number:
            update_payload['policy_number'] = result.policy_number
        if result.claim_number:
            update_payload['claim_number'] = result.claim_number
        
        # GUARDRAIL: Log extracted metadata with PII redacted
        print(f"📋 Extracted metadata:")
        print(f"   Hospital: {redact_pii(str(result.hospital_name or 'NOT FOUND'))}")
        print(f"   Bill #:   {result.bill_number or 'NOT FOUND'}")
        print(f"   Patient:  {redact_pii(str(result.patient_name or 'NOT FOUND'))}")
        
        db.table('analyses').update(update_payload).eq('id', analysis_id).execute()
        
        # Insert issues with comprehensive debugging
        print(f"💾 BEFORE INSERT: Agent returned {len(result.issues)} issues")
        
        for idx, issue in enumerate(result.issues):
            try:
                issue_payload = {
                    'analysis_id': analysis_id,
                    'issue_id': issue.issue_id,
                    'issue_type': issue.issue_type.value if hasattr(issue.issue_type, 'value') else str(issue.issue_type),
                    'description': issue.description,
                    'billed_amount': float(issue.billed_amount) if issue.billed_amount else 0,
                    'benchmark_amount': float(issue.benchmark_amount) if issue.benchmark_amount else None,
                    'overcharge_amount': float(issue.overcharge_amount) if issue.overcharge_amount else None,
                    'confidence': issue.confidence.value if hasattr(issue.confidence, 'value') else str(issue.confidence),
                    'evidence': issue.evidence if isinstance(issue.evidence, list) else [],
                    'action_required': issue.action_required or ''
                }
                
                print(f"💾 Issue {idx+1} payload: {issue_payload}")
                
                result_insert = db.table('issues').insert(issue_payload).execute()
                
                print(f"✅ Issue {idx+1} inserted successfully")
                print(f"✅ Insert result data: {result_insert.data}")
                
            except Exception as insert_error:
                print(f"❌ FAILED to insert issue {idx+1}")
                print(f"❌ Error: {insert_error}")
                import traceback
                print(f"❌ Traceback: {traceback.format_exc()}")
        
        print(f"✅ Analysis {analysis_id} complete: {len(result.issues)} issues")
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"ERROR in _process_analysis: {error_details}")
        
        # Update analysis to failed status so frontend stops polling
        try:
            db.table('analyses').update({
                'status': 'failed',
                'failure_reason': 'server_error'
            }).eq('id', analysis_id).execute()
        except:
            pass


@router.get("/analysis/{analysis_id}")
async def get_analysis(
    analysis_id: str,
    db: Client = Depends(get_db)
):
    """Get analysis results."""
    try:
        result = db.table('analyses').select('*').eq('id', analysis_id).single().execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Analysis not found")
        
        issues = db.table('issues').select('*').eq('analysis_id', analysis_id).execute()
        
        print(f"📤 GET /analysis/{analysis_id} - Returning {len(issues.data)} issues")
        
        return {
            "analysis": result.data,
            "issues": issues.data
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch analysis: {str(e)}")


@router.post("/letters/generate")
async def generate_letters(
    data: LetterGenerate,
    db: Client = Depends(get_db)
):
    """Generate scenario-appropriate letters for an analysis.
    
    Uses LETTER_MATRIX to only generate letters that make sense for this case.
    Validates each letter against the analysis data before saving.
    """
    try:
        analysis = db.table('analyses').select('raw_result').eq('id', data.analysis_id).single().execute()
        
        if not analysis.data:
            raise HTTPException(status_code=404, detail="Analysis not found")
        
        raw_result = analysis.data['raw_result']
        generator = AdaptiveLetterGenerator(raw_result)
        
        # Classify scenario
        scenario = classify_scenario(raw_result, data)
        print(f"📋 Letter generation scenario: {scenario}")
        
        # Determine which letters to generate
        letter_types_to_generate = LETTER_MATRIX[scenario]
        print(f"📋 Letters to generate: {letter_types_to_generate}")
        
        letters = []
        skipped_letters = []
        
        for letter_type in letter_types_to_generate:
            content = None
            
            try:
                if letter_type == 'hospital_clarification':
                    content = generator.generate_hospital_clarification_letter(
                        patient_name=data.patient_name,
                        hospital_name=data.hospital_name or "Hospital Billing Department",
                        bill_number=raw_result.get('bill_number') or data.bill_number or "Not Specified"
                    )
                elif letter_type.startswith('hospital_'):
                    tone = letter_type.replace('hospital_', '')
                    content = generator.generate_hospital_letter(
                        tone=tone,
                        patient_name=data.patient_name,
                        hospital_name=data.hospital_name or "Hospital Billing Department",
                        bill_number=raw_result.get('bill_number') or data.bill_number or "Not Specified"
                    )
                elif letter_type == 'insurer':
                    content = generator.generate_insurer_letter(
                        tone='professional',
                        patient_name=data.patient_name,
                        insurer_name=data.insurer_name or "Insurance Company",
                        policy_number=raw_result.get('policy_number') or data.policy_number or "Not Specified",
                        claim_number=raw_result.get('claim_number') or data.claim_number or "Not Specified"
                    )
                elif letter_type == 'patient_summary':
                    content = generator.generate_patient_summary(
                        patient_name=data.patient_name,
                        scenario=scenario
                    )
                
                if not content:
                    print(f"⚠️ No content generated for {letter_type}")
                    skipped_letters.append({'type': letter_type, 'reason': 'no_content'})
                    continue
                
                # GUARDRAIL: Validate before saving
                is_valid, reason = validate_letter_content(content, scenario, raw_result)
                if not is_valid:
                    print(f"❌ {letter_type} failed validation: {reason}")
                    skipped_letters.append({'type': letter_type, 'reason': reason})
                    continue
                
                # Save to DB
                inserted = db.table('letters').insert({
                    'analysis_id': data.analysis_id,
                    'letter_type': letter_type,
                    'content': content
                }).execute()
                
                letters.append({
                    'id': inserted.data[0]['id'] if inserted.data else None,
                    'letter_type': letter_type,
                    'content': content
                })
                print(f"✅ Generated {letter_type}")
                
            except Exception as e:
                print(f"❌ Error generating {letter_type}: {str(e)}")
                skipped_letters.append({'type': letter_type, 'reason': str(e)})
        
        return {
            "analysis_id": data.analysis_id,
            "scenario": scenario,
            "letters": letters,
            "skipped": skipped_letters
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Letter generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate letters: {str(e)}")


@router.get("/letters/{analysis_id}")
async def get_letters(
    analysis_id: str,
    db: Client = Depends(get_db)
):
    """Get all generated letters for an analysis."""
    try:
        letters = db.table('letters').select('*').eq('analysis_id', analysis_id).execute()
        
        return {
            "letters": letters.data
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch letters: {str(e)}")


@router.get("/letters/{letter_id}/pdf")
async def download_letter_pdf(
    letter_id: str,
    db: Client = Depends(get_db)
):
    """Generate and download a letter as PDF."""
    try:
        # Fetch letter from DB
        letter_result = db.table('letters').select('*').eq('id', letter_id).single().execute()
        
        if not letter_result.data:
            raise HTTPException(status_code=404, detail="Letter not found")
        
        letter = letter_result.data
        content = letter['content']
        letter_type = letter['letter_type']
        
        # Generate PDF in memory
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=1*inch,
            rightMargin=1*inch,
            topMargin=1*inch,
            bottomMargin=1*inch
        )
        
        # Styling
        styles = getSampleStyleSheet()
        body_style = ParagraphStyle(
            'CustomBody',
            parent=styles['Normal'],
            fontSize=11,
            leading=16,
            alignment=TA_LEFT,
            spaceAfter=12
        )
        
        # Convert content to PDF paragraphs (split by double newlines)
        story = []
        paragraphs = content.split('\n\n')
        for para in paragraphs:
            if para.strip():
                # Replace single newlines with <br/> for line breaks within paragraphs
                formatted = para.replace('\n', '<br/>').strip()
                story.append(Paragraph(formatted, body_style))
                story.append(Spacer(1, 0.1*inch))
        
        doc.build(story)
        buffer.seek(0)
        
        # Friendly filename based on letter type
        filename_map = {
            'hospital_clarification': 'Hospital_Clarification_Request.pdf',
            'hospital_polite': 'Hospital_Letter_Polite.pdf',
            'hospital_professional': 'Hospital_Letter_Professional.pdf',
            'hospital_firm': 'Hospital_Letter_Firm.pdf',
            'insurer': 'Insurer_Escalation_Letter.pdf',
            'patient_summary': 'Patient_Action_Plan.pdf'
        }
        filename = filename_map.get(letter_type, f'Letter_{letter_type}.pdf')
        
        return StreamingResponse(
            buffer,
            media_type='application/pdf',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"'
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")