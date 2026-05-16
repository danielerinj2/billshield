#!/usr/bin/env python3
"""
BillShield UX patcher — Day 8.
Save this file as /Users/erin/billshield/public/patch.py and run:
    cd /Users/erin/billshield/public
    python3 patch.py

It backs up index.html → index.html.day7.bak, then applies 8 surgical patches.
If any patch can't find its anchor, the script aborts and your file is untouched.
"""
import sys
import shutil
from pathlib import Path

SRC = Path("index.html")
BAK = Path("index.html.day7.bak")

if not SRC.exists():
    print(f"ERROR: {SRC} not found. cd to /Users/erin/billshield/public first.")
    sys.exit(1)

# Backup
shutil.copy(SRC, BAK)
print(f"✓ Backup: {BAK}")

html = SRC.read_text()

# ----- PATCH 1: replace 4 upload blocks with one + concerns + notes -----
OLD1 = '''                    <div class="form-group">
                        <label>Hospital Bill (Required) *</label>
                        <div class="upload-zone" id="billUpload" onclick="document.getElementById('billFile').click()">
                            <div class="upload-icon">📄</div>
                            <p><strong>Click to upload</strong> or drag and drop</p>
                            <p style="font-size: 0.9rem; color: var(--text-muted); margin-top: 0.5rem;">PDF, JPG, PNG accepted (Max 10MB)</p>
                        </div>
                        <input type="file" id="billFile" style="display: none" accept=".pdf,.jpg,.jpeg,.png" onchange="handleFileSelect(this, 'bill')">
                        <div id="billList" class="file-list"></div>
                    </div>

                    <div class="form-group">
                        <label>Additional Documents (Optional)</label>
                        <div style="display: grid; gap: 1rem;">
                            <div>
                                <p style="font-size: 0.9rem; color: var(--text-muted); margin-bottom: 0.5rem;">Discharge Summary</p>
                                <div class="upload-zone" style="padding: 1.5rem;" onclick="document.getElementById('dischargeFile').click()">
                                    <p>📋 Upload Discharge Summary</p>
                                </div>
                                <input type="file" id="dischargeFile" style="display: none" accept=".pdf,.jpg,.jpeg,.png" onchange="handleFileSelect(this, 'discharge')">
                                <div id="dischargeList" class="file-list"></div>
                            </div>
                            <div>
                                <p style="font-size: 0.9rem; color: var(--text-muted); margin-bottom: 0.5rem;">Insurance Rejection Letter</p>
                                <div class="upload-zone" style="padding: 1.5rem;" onclick="document.getElementById('rejectionFile').click()">
                                    <p>✉️ Upload Rejection Letter</p>
                                </div>
                                <input type="file" id="rejectionFile" style="display: none" accept=".pdf,.jpg,.jpeg,.png" onchange="handleFileSelect(this, 'rejection')">
                                <div id="rejectionList" class="file-list"></div>
                            </div>
                            <div>
                                <p style="font-size: 0.9rem; color: var(--text-muted); margin-bottom: 0.5rem;">Insurance Policy Document</p>
                                <div class="upload-zone" style="padding: 1.5rem;" onclick="document.getElementById('policyFile').click()">
                                    <p>📑 Upload Policy Document</p>
                                </div>
                                <input type="file" id="policyFile" style="display: none" accept=".pdf,.jpg,.jpeg,.png" onchange="handleFileSelect(this, 'policy')">
                                <div id="policyList" class="file-list"></div>
                            </div>
                        </div>
                    </div>'''

NEW1 = '''                    <div class="form-group">
                        <label>Your Documents (up to 5 files)</label>
                        <p style="font-size: 0.9rem; color: var(--text-muted); margin-bottom: 0.75rem;">Upload your hospital bill plus any related documents — discharge summary, insurance rejection letter, or policy. We'll figure out what each one is.</p>
                        <div class="upload-zone" id="multiUpload" onclick="document.getElementById('multiFile').click()">
                            <div class="upload-icon">📄</div>
                            <p><strong>Click to upload</strong> or drag and drop</p>
                            <p style="font-size: 0.9rem; color: var(--text-muted); margin-top: 0.5rem;">PDF, JPG, PNG accepted · Max 10MB per file · Up to 5 files</p>
                        </div>
                        <input type="file" id="multiFile" style="display: none" accept=".pdf,.jpg,.jpeg,.png" multiple onchange="handleMultiFileSelect(this)">
                        <div id="multiList" class="file-list"></div>
                    </div>

                    <div class="form-group">
                        <label>What concerns you about this bill? (Optional)</label>
                        <p style="font-size: 0.9rem; color: var(--text-muted); margin-bottom: 0.75rem;">Tick anything that looked off. We'll focus our checks on these areas.</p>
                        <div class="concerns-grid">
                            <label class="concern-item"><input type="checkbox" name="concern" value="room_rent"> <span>Room rent looked high</span></label>
                            <label class="concern-item"><input type="checkbox" name="concern" value="pharmacy"> <span>Pharmacy / medicines</span></label>
                            <label class="concern-item"><input type="checkbox" name="concern" value="lab_tests"> <span>Lab tests</span></label>
                            <label class="concern-item"><input type="checkbox" name="concern" value="procedure"> <span>Procedure / surgery charges</span></label>
                            <label class="concern-item"><input type="checkbox" name="concern" value="doctor_fees"> <span>Doctor / consultation fees</span></label>
                            <label class="concern-item"><input type="checkbox" name="concern" value="claim_rejected"> <span>Insurance claim was rejected</span></label>
                        </div>
                    </div>

                    <div class="form-group">
                        <label>Anything else we should know? (Optional)</label>
                        <textarea id="userNotes" rows="4" placeholder="e.g. This bill is from my mother's hip surgery in May. The room rent jumped from ₹4,000 to ₹12,000 on day 3 with no explanation." style="width: 100%; padding: 1rem; border: 2px solid var(--border); border-radius: 8px; font-size: 1rem; font-family: inherit; resize: vertical; transition: border-color 0.2s;"></textarea>
                    </div>'''

if OLD1 not in html:
    print("ERROR: Patch 1 anchor not found (upload blocks). Aborted.")
    sys.exit(1)
html = html.replace(OLD1, NEW1)
print("✓ Patch 1: single upload zone + concerns + notes")

# ----- PATCH 2: inject new CSS just before </style> -----
CSS_INJECT = '''
        /* Concerns checkboxes */
        .concerns-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 0.5rem;
        }

        .concern-item {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.75rem 1rem;
            border: 2px solid var(--border);
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
            font-weight: 500;
            font-size: 0.95rem;
        }

        .concern-item:hover {
            border-color: var(--primary);
            background: rgba(37, 99, 235, 0.02);
        }

        .concern-item input[type="checkbox"] {
            width: 18px;
            height: 18px;
            cursor: pointer;
            accent-color: var(--primary);
        }

        .concern-item input[type="checkbox"]:checked + span {
            color: var(--primary);
            font-weight: 600;
        }

        .form-group textarea:focus {
            outline: none;
            border-color: var(--primary);
        }

        .file-item .doc-tag {
            display: inline-block;
            padding: 0.2rem 0.6rem;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 600;
            background: rgba(37, 99, 235, 0.1);
            color: var(--primary);
            margin-left: 0.5rem;
        }

        .file-item .doc-tag.unknown {
            background: rgba(245, 158, 11, 0.1);
            color: #92400E;
        }

    </style>'''

if "    </style>" not in html:
    print("ERROR: Patch 2 anchor not found (</style>). Aborted.")
    sys.exit(1)
html = html.replace("    </style>", CSS_INJECT, 1)
print("✓ Patch 2: new CSS injected")

# ----- PATCH 3: Ankit Kumar -> dynamic patient name -----
OLD3 = '''                        <div class="form-group">
                            <label>Patient Name</label>
                            <input type="text" value="Ankit Kumar" readonly style="background: var(--bg);">
                        </div>'''
NEW3 = '''                        <div class="form-group">
                            <label>Patient Name</label>
                            <input type="text" id="lettersPatientName" readonly style="background: var(--bg);">
                        </div>'''
if OLD3 not in html:
    print("ERROR: Patch 3 anchor not found (Ankit Kumar). Aborted.")
    sys.exit(1)
html = html.replace(OLD3, NEW3)
print("✓ Patch 3: Ankit Kumar removed")

# ----- PATCH 4: relabel Unverified Charges -----
if '<div class="stat-label">Unverified Charges</div>' not in html:
    print("ERROR: Patch 4 anchor not found (Unverified Charges). Aborted.")
    sys.exit(1)
html = html.replace(
    '<div class="stat-label">Unverified Charges</div>',
    '<div class="stat-label">Amount not yet checked</div>',
)
print("✓ Patch 4: Unverified Charges relabeled")

# ----- PATCH 5: dispute button id + no-issues panel -----
OLD5 = '<button class="btn btn-primary btn-large" style="width: 100%; margin-top: 2rem;" onclick="showPage(\'letters\')">Generate Dispute Letters →</button>'
NEW5 = ('<button id="generateLettersBtn" class="btn btn-primary btn-large" style="width: 100%; margin-top: 2rem;" onclick="showPage(\'letters\')">Generate Dispute Letters →</button>\n\n'
        '                <div id="noIssuesPanel" style="display: none; background: var(--bg); padding: 2rem; border-radius: 12px; margin-top: 2rem; text-align: center;">\n'
        '                    <h3 style="margin-bottom: 0.5rem;">Nothing to dispute here</h3>\n'
        '                    <p id="noIssuesMessage" style="color: var(--text-muted); line-height: 1.7;"></p>\n'
        '                </div>')
if OLD5 not in html:
    print("ERROR: Patch 5 anchor not found (Generate Dispute Letters). Aborted.")
    sys.exit(1)
html = html.replace(OLD5, NEW5)
print("✓ Patch 5: dispute button id + no-issues panel")

# ----- PATCH 6: global state -----
OLD6 = '''        // Global state
        let uploadedFiles = {
            bill: null,
            discharge: null,
            rejection: null,
            policy: null
        };
        let selectedTone = 'professional';'''

NEW6 = '''        // Global state
        let uploadedFiles = [];   // array of { file, docType } — up to 5
        let selectedTone = 'professional';
        const MAX_FILES = 5;

        function classifyByFilename(name) {
            const n = name.toLowerCase();
            if (/(discharge|summary|dis[-_ ]?sum)/.test(n)) return 'discharge';
            if (/(reject|denial|repud|denied)/.test(n)) return 'rejection';
            if (/(policy|certificate|cert)/.test(n)) return 'policy';
            if (/(bill|invoice|receipt|tax|charges|hospital|lab|pharm)/.test(n)) return 'bill';
            return 'unknown';
        }

        const DOC_TYPE_LABELS = {
            bill: 'Hospital Bill',
            discharge: 'Discharge Summary',
            rejection: 'Rejection Letter',
            policy: 'Policy Document',
            unknown: 'Will auto-detect'
        };'''

if OLD6 not in html:
    print("ERROR: Patch 6 anchor not found (global state). Aborted.")
    sys.exit(1)
html = html.replace(OLD6, NEW6)
print("✓ Patch 6: global state replaced")

# ----- PATCH 7: file handlers -----
OLD7 = '''        // File Upload Handling
        function handleFileSelect(input, type) {
            const file = input.files[0];
            if (file) {
                uploadedFiles[type] = file;
                displayFile(file, type);
            }
        }

        function displayFile(file, type) {
            const listId = type + 'List';
            const list = document.getElementById(listId);
            list.innerHTML = `
                <div class="file-item">
                    <div>
                        <div class="name">${file.name}</div>
                        <div class="size">${(file.size / 1024 / 1024).toFixed(2)} MB</div>
                    </div>
                    <div class="remove-file" onclick="removeFile('${type}')">Remove</div>
                </div>
            `;
        }

        function removeFile(type) {
            uploadedFiles[type] = null;
            document.getElementById(type + 'List').innerHTML = '';
            document.getElementById(type + 'File').value = '';
        }'''

NEW7 = '''        // Multi-file upload handling
        function handleMultiFileSelect(input) {
            const newFiles = Array.from(input.files);
            for (const file of newFiles) {
                if (uploadedFiles.length >= MAX_FILES) {
                    alert(`You can upload up to ${MAX_FILES} files. Remove one before adding more.`);
                    break;
                }
                if (file.size > 10 * 1024 * 1024) {
                    alert(`"${file.name}" is larger than 10MB. Please compress it or upload a smaller file.`);
                    continue;
                }
                uploadedFiles.push({ file, docType: classifyByFilename(file.name) });
            }
            input.value = '';
            renderMultiFileList();
        }

        function renderMultiFileList() {
            const list = document.getElementById('multiList');
            if (!list) return;
            if (uploadedFiles.length === 0) { list.innerHTML = ''; return; }
            list.innerHTML = uploadedFiles.map((entry, idx) => {
                const tagClass = entry.docType === 'unknown' ? 'doc-tag unknown' : 'doc-tag';
                const label = DOC_TYPE_LABELS[entry.docType] || 'Document';
                const sizeMB = (entry.file.size / 1024 / 1024).toFixed(2);
                return `
                    <div class="file-item">
                        <div>
                            <div class="name">${entry.file.name}<span class="${tagClass}">${label}</span></div>
                            <div class="size">${sizeMB} MB</div>
                        </div>
                        <div class="remove-file" onclick="removeMultiFile(${idx})">Remove</div>
                    </div>
                `;
            }).join('');
        }

        function removeMultiFile(idx) {
            uploadedFiles.splice(idx, 1);
            renderMultiFileList();
        }

        // Legacy single-file handlers — kept for any leftover callers.
        function handleFileSelect(input, type) { /* deprecated */ }
        function displayFile(file, type) { /* deprecated */ }
        function removeFile(type) { /* deprecated */ }'''

if OLD7 not in html:
    print("ERROR: Patch 7 anchor not found (file handlers). Aborted.")
    sys.exit(1)
html = html.replace(OLD7, NEW7)
print("✓ Patch 7: file handlers replaced")

# ----- PATCH 8a: handleUpload -----
OLD8A = '''window.handleUpload = async function(event) {
    event.preventDefault();
    
    const patientName = document.getElementById('patientName').value;
    const billFile = document.getElementById('billFile').files[0];
    const dischargeFile = document.getElementById('dischargeFile').files[0];
    const rejectionFile = document.getElementById('rejectionFile').files[0];
    const policyFile = document.getElementById('policyFile').files[0];
    
    if (!patientName || !billFile) {
        alert('Please enter patient name and upload bill');
        return;
    }
    
    try {
        document.getElementById('upload').classList.remove('active');
        document.getElementById('analyzing').classList.add('active');
        
        updateStatus('Creating analysis...');
        const analysisId = await createAnalysis(patientName);
        if (!analysisId) return;
        
        updateStatus('Uploading hospital bill...');
        const billUploaded = await uploadDocument(analysisId, billFile, 'bill');
        if (!billUploaded) {
            alert('Failed to upload bill');
            return;
        }
        
        if (dischargeFile) {
            updateStatus('Uploading discharge summary...');
            await uploadDocument(analysisId, dischargeFile, 'discharge');
        }
        if (rejectionFile) {
            updateStatus('Uploading rejection letter...');
            await uploadDocument(analysisId, rejectionFile, 'rejection');
        }
        if (policyFile) {
            updateStatus('Uploading policy document...');
            await uploadDocument(analysisId, policyFile, 'policy');
        }
        
        updateStatus('Starting AI analysis...');
        const started = await runAnalysis(analysisId);
        if (!started) {
            alert('Failed to start analysis');
            return;
        }
        
        updateStatus('Analyzing against 8,047 benchmarks...');
        const results = await waitForResults(analysisId, (progress) => {
            updateProgress(progress);
        });
        
        displayResults(results);
        window.currentAnalysisId = analysisId;
        
        document.getElementById('analyzing').classList.remove('active');
        document.getElementById('results').classList.add('active');
        
    } catch (error) {
        console.error('Analysis workflow error:', error);
        alert('Analysis failed: ' + error.message);
        document.getElementById('analyzing').classList.remove('active');
        document.getElementById('upload').classList.add('active');
    }
}'''

NEW8A = '''window.handleUpload = async function(event) {
    event.preventDefault();

    const patientName = document.getElementById('patientName').value.trim();

    if (!patientName) { alert('Please enter the patient name.'); return; }
    if (uploadedFiles.length === 0) { alert('Please upload at least one document (the hospital bill).'); return; }
    const hasBillCandidate = uploadedFiles.some(e => e.docType === 'bill' || e.docType === 'unknown');
    if (!hasBillCandidate) {
        alert("We don't see a hospital bill in your uploads. Please add the bill itself, not just supporting documents.");
        return;
    }

    const concerns = Array.from(document.querySelectorAll('input[name="concern"]:checked')).map(c => c.value);
    const userNotes = (document.getElementById('userNotes')?.value || '').trim();
    window.billShieldContext = { patientName, concerns, userNotes };

    try {
        document.getElementById('upload').classList.remove('active');
        document.getElementById('analyzing').classList.add('active');

        updateStatus('Creating analysis...');
        const analysisId = await createAnalysis(patientName);
        if (!analysisId) return;

        for (let i = 0; i < uploadedFiles.length; i++) {
            const entry = uploadedFiles[i];
            const wireType = entry.docType === 'unknown' ? 'bill' : entry.docType;
            updateStatus(`Uploading ${entry.file.name} (${i + 1} of ${uploadedFiles.length})...`);
            const ok = await uploadDocument(analysisId, entry.file, wireType);
            if (!ok && i === 0) { alert('Failed to upload the first document. Please try again.'); return; }
        }

        updateStatus('Starting AI analysis...');
        const started = await runAnalysis(analysisId);
        if (!started) { alert('Failed to start analysis'); return; }

        updateStatus('Analyzing against 8,047 benchmarks...');
        const results = await waitForResults(analysisId, (progress) => { updateProgress(progress); });

        displayResults(results);
        window.currentAnalysisId = analysisId;

        document.getElementById('analyzing').classList.remove('active');
        document.getElementById('results').classList.add('active');

    } catch (error) {
        console.error('Analysis workflow error:', error);
        alert('Analysis failed: ' + error.message);
        document.getElementById('analyzing').classList.remove('active');
        document.getElementById('upload').classList.add('active');
    }
}'''

if OLD8A not in html:
    print("ERROR: Patch 8a anchor not found (handleUpload). Aborted.")
    sys.exit(1)
html = html.replace(OLD8A, NEW8A)
print("✓ Patch 8a: handleUpload rewritten")

# ----- PATCH 8b: displayResults -----
OLD8B = '''function displayResults(results) {
    const analysis = results.analysis;
    const issues = results.issues || [];
    const totalBillEl = document.getElementById('totalBill');
if (totalBillEl) {
    totalBillEl.textContent = (analysis.bill_total || 0).toLocaleString('en-IN');
}

const confirmedOverchargeEl = document.getElementById('confirmedOvercharge');
if (confirmedOverchargeEl) {
    confirmedOverchargeEl.textContent = (analysis.verified_overcharge || 0).toLocaleString('en-IN');
}

const unverifiedChargesEl = document.getElementById('unverifiedCharges');
if (unverifiedChargesEl) {
    const rawResult = analysis.raw_result || {};

    const unverifiedTotal = rawResult.total_unverified_charges !== undefined
        ? rawResult.total_unverified_charges
        : issues
            .filter(issue => issue.confidence !== 'high')
            .reduce((sum, issue) => sum + Number(issue.overcharge_amount || 0), 0);

    unverifiedChargesEl.textContent = unverifiedTotal.toLocaleString('en-IN');
}

    console.log('📊 REAL API Response:', analysis);
    console.log('📋 Issues Array:', issues);

    const summaryValues = document.querySelectorAll('.summary-value');
    if (summaryValues[0]) summaryValues[0].textContent = '₹' + (analysis.bill_total || 0).toLocaleString('en-IN');
    if (summaryValues[1]) summaryValues[1].textContent = '₹' + (analysis.insurance_approved || 0).toLocaleString('en-IN');
    if (summaryValues[2]) summaryValues[2].textContent = '₹' + (analysis.patient_liability || 0).toLocaleString('en-IN');

    const overchargeAmount = document.querySelector('.overcharge-amount');
    if (overchargeAmount) {
        overchargeAmount.textContent = '₹' + (analysis.verified_overcharge || 0).toLocaleString('en-IN');
    }

    const recoveryText = document.querySelector('.recovery-potential');
    if (recoveryText && analysis.verified_overcharge > 0) {
        const minPct = Math.round((analysis.min_recoverable / analysis.verified_overcharge) * 100);
        const maxPct = Math.round((analysis.max_recoverable / analysis.verified_overcharge) * 100);
        recoveryText.textContent = `Recovery Potential: ${minPct}-${maxPct}% (₹${(analysis.min_recoverable || 0).toLocaleString('en-IN')}-₹${(analysis.max_recoverable || 0).toLocaleString('en-IN')})`;
    }

    // HIGH CONFIDENCE
    const highContainer = document.querySelector('.high-confidence .issues-list');
    if (highContainer) {
        const highIssues = issues.filter(i => i.confidence === 'high');
        highContainer.innerHTML = highIssues.map(renderIssueCard).join('');
        const highBadge = document.querySelector('.high-confidence .badge');
        if (highBadge) highBadge.textContent = `${highIssues.length} Issues Found`;
    }

    // MEDIUM CONFIDENCE
    const medContainer = document.querySelector('.medium-confidence .issues-list');
    if (medContainer) {
        const medIssues = issues.filter(i => i.confidence === 'medium');
        medContainer.innerHTML = medIssues.map(renderIssueCard).join('');
        const medBadge = document.querySelector('.medium-confidence .badge');
        if (medBadge) medBadge.textContent = `${medIssues.length} Issues Found`;
    }

    // LOW CONFIDENCE (NEW)
    const lowContainer = document.querySelector('.low-confidence .issues-list');
    if (lowContainer) {
        const lowIssues = issues.filter(i => i.confidence === 'low');
        lowContainer.innerHTML = lowIssues.map(renderIssueCard).join('');
        const lowBadge = document.querySelector('.low-confidence .badge');
        if (lowBadge) lowBadge.textContent = `${lowIssues.length} Items Found`;
    }

    console.log('✅ PAGE UPDATED WITH CONFIDENCE-WEIGHTED CARDS');
}'''

NEW8B = '''function displayResults(results) {
    const analysis = results.analysis || {};
    const issues = results.issues || [];
    const docType = (analysis.doc_type || analysis.document_type || '').toLowerCase();
    const issueCount = issues.length;
    const overchargeAmount = Number(analysis.verified_overcharge || 0);

    const totalBillEl = document.getElementById('totalBill');
    if (totalBillEl) totalBillEl.textContent = (analysis.bill_total || 0).toLocaleString('en-IN');

    const confirmedOverchargeEl = document.getElementById('confirmedOvercharge');
    if (confirmedOverchargeEl) confirmedOverchargeEl.textContent = overchargeAmount.toLocaleString('en-IN');

    const unverifiedChargesEl = document.getElementById('unverifiedCharges');
    if (unverifiedChargesEl) {
        const rawResult = analysis.raw_result || {};
        const unverifiedTotal = rawResult.total_unverified_charges !== undefined
            ? rawResult.total_unverified_charges
            : issues.filter(issue => issue.confidence !== 'high')
                    .reduce((sum, issue) => sum + Number(issue.overcharge_amount || 0), 0);
        unverifiedChargesEl.textContent = unverifiedTotal.toLocaleString('en-IN');
    }

    const headlineEl = document.querySelector('.financial-summary h1');
    const recoveryAmountEl = document.querySelector('.overcharge-amount');
    const recoveryTextEl = document.querySelector('.recovery-potential');
    const recoveryHighlight = document.querySelector('.recovery-highlight');
    const recoveryHeading = recoveryHighlight ? recoveryHighlight.querySelector('h2') : null;

    if (docType === 'lab') {
        if (headlineEl) headlineEl.textContent = 'Lab bill read';
        if (recoveryHeading) recoveryHeading.textContent = 'Price checks not yet supported';
        if (recoveryAmountEl) recoveryAmountEl.textContent = '—';
        if (recoveryTextEl) recoveryTextEl.textContent = "We read your lab bill, but pricing benchmarks for lab tests aren't live yet. We're building them next. You'll get a check when they're ready.";
    } else if (issueCount === 0) {
        if (headlineEl) headlineEl.textContent = 'No overcharges found';
        if (recoveryHeading) recoveryHeading.textContent = '✓ Your bill checks out';
        if (recoveryAmountEl) recoveryAmountEl.textContent = '₹0';
        if (recoveryTextEl) recoveryTextEl.textContent = "We ran our checks against CGHS rates, NPPA ceilings, and insurance regulations and didn't find any overcharges in this bill.";
    } else {
        if (headlineEl) headlineEl.textContent = 'Analysis Complete';
        if (recoveryHeading) recoveryHeading.textContent = '✓ Overcharges Found';
        if (recoveryAmountEl) recoveryAmountEl.textContent = '₹' + overchargeAmount.toLocaleString('en-IN');
        if (recoveryTextEl && overchargeAmount > 0) {
            const minPct = Math.round((analysis.min_recoverable / overchargeAmount) * 100);
            const maxPct = Math.round((analysis.max_recoverable / overchargeAmount) * 100);
            recoveryTextEl.textContent = `Recovery Potential: ${minPct}-${maxPct}% (₹${(analysis.min_recoverable || 0).toLocaleString('en-IN')}-₹${(analysis.max_recoverable || 0).toLocaleString('en-IN')})`;
        } else if (recoveryTextEl) {
            recoveryTextEl.textContent = `${issueCount} ${issueCount === 1 ? 'issue' : 'issues'} flagged for review below.`;
        }
    }

    const generateBtn = document.getElementById('generateLettersBtn');
    const noIssuesPanel = document.getElementById('noIssuesPanel');
    const noIssuesMsg = document.getElementById('noIssuesMessage');
    if (issueCount === 0) {
        if (generateBtn) generateBtn.style.display = 'none';
        if (noIssuesPanel) noIssuesPanel.style.display = 'block';
        if (noIssuesMsg) {
            noIssuesMsg.textContent = docType === 'lab'
                ? "Once lab benchmarks are live, we'll re-analyze this bill and let you know."
                : "There's nothing to dispute in this bill based on our current checks. If something still looks wrong to you, you can request an itemized breakdown from the hospital.";
        }
    } else {
        if (generateBtn) generateBtn.style.display = '';
        if (noIssuesPanel) noIssuesPanel.style.display = 'none';
    }

    const groups = [
        { sel: '.high-confidence', confidence: 'high', labelMany: 'Issues Found' },
        { sel: '.medium-confidence', confidence: 'medium', labelMany: 'Issues Found' },
        { sel: '.low-confidence', confidence: 'low', labelMany: 'Items Found' },
    ];
    for (const g of groups) {
        const container = document.querySelector(`${g.sel} .issues-list`);
        const group = document.querySelector(g.sel);
        if (!container || !group) continue;
        const filtered = issues.filter(i => i.confidence === g.confidence);
        container.innerHTML = filtered.map(renderIssueCard).join('');
        const badge = group.querySelector('.badge');
        if (badge) badge.textContent = `${filtered.length} ${g.labelMany}`;
        group.style.display = (filtered.length === 0 && issueCount > 0) ? 'none' : '';
        if (issueCount === 0) group.style.display = 'none';
    }

    const lettersPatientNameEl = document.getElementById('lettersPatientName');
    const ctx = window.billShieldContext || {};
    if (lettersPatientNameEl) lettersPatientNameEl.value = ctx.patientName || analysis.patient_name || '';

    console.log('📊 API Response:', analysis);
    console.log('📋 Issues:', issues);
    console.log(`✅ Rendered — docType=${docType}, issues=${issueCount}, overcharge=₹${overchargeAmount}`);
}'''

if OLD8B not in html:
    print("ERROR: Patch 8b anchor not found (displayResults). Aborted.")
    sys.exit(1)
html = html.replace(OLD8B, NEW8B)
print("✓ Patch 8b: displayResults rewritten")

# Write
SRC.write_text(html)
print(f"\n✅ Patched index.html ({len(html):,} bytes)")
print(f"   Backup at {BAK}")
print(f"\nNext: open index.html in your browser to smoke test, then:")
print("   git add public/index.html")
print('   git commit -m "UX cleanup: single upload zone, concerns checkboxes, state-aware results"')
print("   git push origin main")
