"""Pydantic models for API requests/responses."""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


class AnalysisCreate(BaseModel):
    """Request to create a new analysis."""
    patient_name: str
    hospital_name: Optional[str] = None
    bill_number: Optional[str] = None
    policy_number: Optional[str] = None
    claim_number: Optional[str] = None


class DocumentUpload(BaseModel):
    """Document upload metadata."""
    doc_type: str = Field(..., pattern="^(bill|discharge|rejection|policy)$")
    file_path: str


class AnalysisResult(BaseModel):
    """Analysis result from agent."""
    analysis_id: str
    status: str
    bill_total: float
    insurance_approved: float
    insurance_rejected: float
    patient_liability: float
    verified_overcharge: float
    min_recoverable: float
    max_recoverable: float
    issues_count: int
    created_at: datetime


class IssueDetail(BaseModel):
    """Individual issue detail."""
    issue_id: str
    issue_type: str
    description: str
    overcharge_amount: float
    confidence: str
    evidence: List[str]
    action_required: str


"""Request to generate letters."""
class LetterGenerate(BaseModel):
    analysis_id: str
    tone: str = Field(default="professional", pattern="^(polite|professional|firm)$")
    patient_name: str
    hospital_name: Optional[str] = None
    insurer_name: Optional[str] = None
    bill_number: Optional[str] = None
    policy_number: Optional[str] = None
    claim_number: Optional[str] = None


class LetterResponse(BaseModel):
    """Generated letter response."""
    letter_type: str
    content: str
    generated_at: datetime