-- BillShield Database Schema
-- Run this in Supabase SQL Editor

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users table (managed by Supabase Auth, but we add profile info)
CREATE TABLE public.user_profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    full_name TEXT,
    phone TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Analyses table (one per bill upload)
CREATE TABLE public.analyses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    status TEXT CHECK (status IN ('processing', 'complete', 'failed')) DEFAULT 'processing',
    
    -- Financial summary
    bill_total NUMERIC(12,2),
    insurance_approved NUMERIC(12,2),
    insurance_rejected NUMERIC(12,2),
    patient_liability NUMERIC(12,2),
    verified_overcharge NUMERIC(12,2),
    min_recoverable NUMERIC(12,2),
    max_recoverable NUMERIC(12,2),
    
    -- Store full agent result as JSON
    raw_result JSONB,
    
    -- User-provided context
    patient_name TEXT,
    hospital_name TEXT,
    bill_number TEXT,
    policy_number TEXT,
    claim_number TEXT
);

-- Documents table (uploaded PDFs)
CREATE TABLE public.documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id UUID NOT NULL REFERENCES public.analyses(id) ON DELETE CASCADE,
    doc_type TEXT CHECK (doc_type IN ('bill', 'discharge', 'rejection', 'policy')) NOT NULL,
    file_path TEXT NOT NULL,  -- Supabase Storage path
    file_size INTEGER,
    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);

-- Issues table (individual detected issues)
CREATE TABLE public.issues (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id UUID NOT NULL REFERENCES public.analyses(id) ON DELETE CASCADE,
    issue_id TEXT NOT NULL,  -- e.g., "DEVICE_006"
    issue_type TEXT NOT NULL,  -- e.g., "device_overcharge"
    description TEXT NOT NULL,
    billed_amount NUMERIC(12,2),
    benchmark_amount NUMERIC(12,2),
    overcharge_amount NUMERIC(12,2),
    confidence TEXT CHECK (confidence IN ('high', 'medium', 'low')) NOT NULL,
    evidence JSONB,  -- Array of evidence strings
    action_required TEXT
);

-- Generated letters table
CREATE TABLE public.letters (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id UUID NOT NULL REFERENCES public.analyses(id) ON DELETE CASCADE,
    letter_type TEXT CHECK (letter_type IN ('hospital_polite', 'hospital_professional', 'hospital_firm', 'insurer', 'patient_summary')) NOT NULL,
    content TEXT NOT NULL,
    generated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Audit trail
CREATE TABLE public.audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,  -- 'file_upload', 'analysis_run', 'letter_download'
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB
);

-- Regulation cache (for Tavily verification tracking)
CREATE TABLE public.regulation_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    regulation_name TEXT UNIQUE NOT NULL,
    content TEXT,
    source_url TEXT,
    last_verified TIMESTAMPTZ DEFAULT NOW(),
    verified_by TEXT,  -- 'manual' or 'tavily'
    is_current BOOLEAN DEFAULT true
);

-- Indexes for performance
CREATE INDEX idx_analyses_user_id ON public.analyses(user_id);
CREATE INDEX idx_analyses_created_at ON public.analyses(created_at DESC);
CREATE INDEX idx_documents_analysis_id ON public.documents(analysis_id);
CREATE INDEX idx_issues_analysis_id ON public.issues(analysis_id);
CREATE INDEX idx_letters_analysis_id ON public.letters(analysis_id);
CREATE INDEX idx_audit_log_user_id ON public.audit_log(user_id);
CREATE INDEX idx_audit_log_timestamp ON public.audit_log(timestamp DESC);

-- Row Level Security (RLS) Policies
ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.issues ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.letters ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY;

-- Users can only see their own data
CREATE POLICY "Users can view own profile"
    ON public.user_profiles FOR SELECT
    USING (auth.uid() = id);

CREATE POLICY "Users can update own profile"
    ON public.user_profiles FOR UPDATE
    USING (auth.uid() = id);

CREATE POLICY "Users can view own analyses"
    ON public.analyses FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can create own analyses"
    ON public.analyses FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can view own documents"
    ON public.documents FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.analyses
            WHERE analyses.id = documents.analysis_id
            AND analyses.user_id = auth.uid()
        )
    );

CREATE POLICY "Users can upload own documents"
    ON public.documents FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.analyses
            WHERE analyses.id = documents.analysis_id
            AND analyses.user_id = auth.uid()
        )
    );

CREATE POLICY "Users can view own issues"
    ON public.issues FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.analyses
            WHERE analyses.id = issues.analysis_id
            AND analyses.user_id = auth.uid()
        )
    );

CREATE POLICY "Users can view own letters"
    ON public.letters FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.analyses
            WHERE analyses.id = letters.analysis_id
            AND analyses.user_id = auth.uid()
        )
    );

CREATE POLICY "Users can view own audit logs"
    ON public.audit_log FOR SELECT
    USING (auth.uid() = user_id);

-- Regulation cache is public read (for all users to see current regulations)
CREATE POLICY "Anyone can view regulations"
    ON public.regulation_cache FOR SELECT
    USING (true);

-- Only service role can update regulations
CREATE POLICY "Service role can update regulations"
    ON public.regulation_cache FOR ALL
    USING (auth.jwt() ->> 'role' = 'service_role');