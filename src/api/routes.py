"""FastAPI routes for BillShield."""

import json
import os
import tempfile
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form
from fastapi.responses import JSONResponse
from supabase import Client

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
    db: Client = Depends(get_db)
):
    """Create a new analysis record."""
    try:
        result = db.table('analyses').insert({
            'status': 'processing',
            'patient_name': data.patient_name,
            'hospital_name': data.hospital_name,
            'bill_number': data.bill_number,
            'policy_number': data.policy_number,
            'claim_number': data.claim_number
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
    Parse a document using 3-tier fallback system:
    1. Regex parser (fast, cheap)
    2. Standard vision LLM (Anthropic/OpenAI)
    3. Groq vision (final fallback for difficult scans)
    """
    if doc_type == 'bill':
        if is_image:
            print("📸 Image file - using vision LLM...")
            return parse_pdf_with_vision(temp_file_path, doc_type='bill')
        
        # TIER 1: Try regex parser first for PDFs
        try:
            print("🔍 TIER 1: Attempting regex parser...")
            data = parse_bill_pdf(temp_file_path)
            line_count = len(data.get('line_items', []))
            
            # Quality check: Verify we got meaningful data
            has_amounts = any(
                item.get('amount', 0) > 0 
                for item in data.get('line_items', [])
            )
            has_descriptions = any(
                len(item.get('description', '').strip()) > 3
                for item in data.get('line_items', [])
            )
            
            if line_count == 0 or not (has_amounts and has_descriptions):
                print(f"⚠️ Regex returned low-quality data (items={line_count}, has_amounts={has_amounts}, has_descriptions={has_descriptions})")
                raise ValueError("Regex quality check failed")
            
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
                    print("🔍 TIER 3: Attempting Groq vision (final fallback)...")
                    from src.scripts.groq_vision_parser import parse_with_groq_vision
                    
                    data = parse_with_groq_vision(temp_file_path, doc_type='bill')
                    line_count = len(data.get('line_items', []))
                    
                    if line_count > 0:
                        print(f"✅ TIER 3 SUCCESS: Groq vision extracted {line_count} items")
                        return data
                    else:
                        raise ValueError("All parsers failed")
                        
                except Exception as groq_error:
                    print(f"❌ TIER 3 FAILED: {groq_error}")
                    print("❌ ALL PARSING TIERS EXHAUSTED")
                    raise ValueError(f"All parsers failed: Regex={regex_error}, Vision={vision_error}, Groq={groq_error}")
    
    elif doc_type == 'discharge':
        if is_image:
            return parse_pdf_with_vision(temp_file_path, doc_type='discharge')
        
        try:
            data = parse_discharge_pdf(temp_file_path)
            if not data.get('patient_info', {}).get('name'):
                raise ValueError("Discharge regex quality check failed")
            return data
        except Exception as e1:
            try:
                return parse_pdf_with_vision(temp_file_path, doc_type='discharge')
            except Exception as e2:
                from src.scripts.groq_vision_parser import parse_with_groq_vision
                return parse_with_groq_vision(temp_file_path, doc_type='discharge')
    
    elif doc_type == 'rejection':
        if is_image:
            return parse_pdf_with_vision(temp_file_path, doc_type='rejection')
        
        try:
            data = parse_rejection_pdf(temp_file_path)
            if not data.get('claim_metadata', {}).get('claim_number'):
                raise ValueError("Rejection regex quality check failed")
            return data
        except Exception as e1:
            try:
                return parse_pdf_with_vision(temp_file_path, doc_type='rejection')
            except Exception as e2:
                from src.scripts.groq_vision_parser import parse_with_groq_vision
                return parse_with_groq_vision(temp_file_path, doc_type='rejection')
    
    return None


@router.post("/analysis/run/{analysis_id}")
async def run_analysis(
    analysis_id: str,
    db: Client = Depends(get_db)
):
    """Run BillShield agent on uploaded documents."""
    try:
        # Get documents for this analysis
        docs = db.table('documents').select('*').eq('analysis_id', analysis_id).execute()
        
        if not docs.data:
            raise HTTPException(status_code=404, detail="No documents found")
        
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
            raise HTTPException(
                status_code=400, 
                detail="Could not parse hospital bill. Please check the file format."
            )
        
        print(f"📋 Documents parsed:")
        print(f"   Bill: {'✓' if bill_data else '✗'}")
        print(f"   Discharge: {'✓' if discharge_data else '✗'}")
        print(f"   Rejection: {'✓' if rejection_data else '✗'}")
        
        # DEBUG: Show what vision parser returned BEFORE agent runs
        print("="*80)
        print("🔍 DEBUG: VISION PARSER OUTPUT")
        print("="*80)
        print(json.dumps(bill_data, indent=2))
        print("="*80)
        
        # Initialize RAG and agent
        rag = BillShieldRAG()
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
        
        # Update analysis record
        db.table('analyses').update({
            'status': 'complete',
            'bill_total': result.total_bill,
            'insurance_approved': result.total_approved,
            'insurance_rejected': result.total_rejected,
            'patient_liability': result.total_patient_liability,
            'verified_overcharge': result.total_verified_overcharge,
            'min_recoverable': result.estimated_recoverable['min'],
            'max_recoverable': result.estimated_recoverable['max'],
            'raw_result': result.to_dict()
        }).eq('id', analysis_id).execute()
        
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
        
        return {
            "analysis_id": analysis_id,
            "status": "complete",
            "issues_count": len(result.issues),
            "verified_overcharge": result.total_verified_overcharge
        }
    
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"ERROR in run_analysis: {error_details}")
        
        # Update analysis to failed status
        try:
            db.table('analyses').update({
                'status': 'failed'
            }).eq('id', analysis_id).execute()
        except:
            pass
        
        raise HTTPException(status_code=500, detail=f"Failed to run analysis: {str(e)}")


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
    """Generate all letters for an analysis."""
    try:
        analysis = db.table('analyses').select('raw_result').eq('id', data.analysis_id).single().execute()
        
        if not analysis.data:
            raise HTTPException(status_code=404, detail="Analysis not found")
        
        generator = AdaptiveLetterGenerator(analysis.data['raw_result'])
        
        letters = []
        
        # Hospital letters (3 tones)
        for tone in ['polite', 'professional', 'firm']:
            content = generator.generate_hospital_letter(
                tone=tone,
                patient_name=data.patient_name,
                hospital_name=data.hospital_name or "[Hospital Name]",
                bill_number=analysis.data['raw_result'].get('bill_number', '[Bill Number]')
            )
            
            db.table('letters').insert({
                'analysis_id': data.analysis_id,
                'letter_type': f'hospital_{tone}',
                'content': content
            }).execute()
            
            letters.append({
                'letter_type': f'hospital_{tone}',
                'content': content
            })
        
        # Insurer letter
        insurer_letter = generator.generate_insurer_letter(
            tone='firm',
            patient_name=data.patient_name,
            insurer_name=data.insurer_name or "[Insurance Company]",
            policy_number=analysis.data['raw_result'].get('policy_number', '[Policy Number]'),
            claim_number=analysis.data['raw_result'].get('claim_number', '[Claim Number]')
        )
        
        db.table('letters').insert({
            'analysis_id': data.analysis_id,
            'letter_type': 'insurer',
            'content': insurer_letter
        }).execute()
        
        letters.append({
            'letter_type': 'insurer',
            'content': insurer_letter
        })
        
        # Patient summary
        patient_summary = generator.generate_patient_summary(
            patient_name=data.patient_name
        )
        
        db.table('letters').insert({
            'analysis_id': data.analysis_id,
            'letter_type': 'patient_summary',
            'content': patient_summary
        }).execute()
        
        letters.append({
            'letter_type': 'patient_summary',
            'content': patient_summary
        })
        
        return {
            "analysis_id": data.analysis_id,
            "letters": letters
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Letter generation failed: {str(e)}")


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