"""
Generate a synthetic hospital discharge summary PDF for testing BillShield.

Models Ankit's scenario:
- 45M, emergency CABG x3, 8-day stay (3 days ICU + 4 days private ward)
- Matches the procedures, dates, and ward types in test_bill_ankit.pdf

Output: data/samples/test_discharge_ankit.pdf

Run from project root:
    python -m tests.fixtures.generate_test_discharge
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


def generate_discharge():
    project_root = Path(__file__).parent.parent.parent
    output_path = project_root / "data" / "samples" / "test_discharge_ankit.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=1.8*cm,
        leftMargin=1.8*cm,
        topMargin=1.5*cm,
        bottomMargin=1.5*cm,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'Title', parent=styles['Title'],
        fontSize=15, spaceAfter=4, alignment=1,
    )
    subtitle_style = ParagraphStyle(
        'Subtitle', parent=styles['Normal'],
        fontSize=9, alignment=1, spaceAfter=8, textColor=colors.grey,
    )
    section_style = ParagraphStyle(
        'Section', parent=styles['Normal'],
        fontSize=11, spaceBefore=10, spaceAfter=6,
        textColor=colors.HexColor('#2C3E50'),
        fontName='Helvetica-Bold',
    )
    body_style = ParagraphStyle(
        'Body', parent=styles['Normal'],
        fontSize=10, spaceAfter=6, leading=14,
    )

    elements = []

    # --- Header ---
    elements.append(Paragraph("CITY CARE HOSPITAL", title_style))
    elements.append(Paragraph(
        "123 Health Boulevard, Andheri West, Mumbai - 400058 | NABH Accredited",
        subtitle_style
    ))
    elements.append(Paragraph(
        "<b>DISCHARGE SUMMARY</b>",
        ParagraphStyle('DocTitle', parent=styles['Normal'], fontSize=12,
                       alignment=1, spaceAfter=12)
    ))

    # --- Patient Information Table ---
    patient_info = [
        ["Patient Name:", "Ankit Sharma", "Age / Sex:", "45 Years / Male"],
        ["MRN / Patient ID:", "CCH-IP-2025-1247", "Bill Number:", "CCH/2025/03/4821"],
        ["Admission Date:", "11/03/2025", "Discharge Date:", "18/03/2025"],
        ["Length of Stay:", "7 days", "Ward(s):", "ICU (3d), Private Deluxe (4d)"],
        ["Consultant:", "Dr. Rajesh Mehta, MD DM (Cardiology)", "", ""],
        ["Attending Surgeon:", "Dr. Vikram Singh, MS MCh (CTVS)", "", ""],
    ]

    patient_table = Table(patient_info, colWidths=[3.8*cm, 5*cm, 3.2*cm, 5*cm])
    patient_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(patient_table)

    # --- Diagnosis ---
    elements.append(Paragraph("FINAL DIAGNOSIS", section_style))
    elements.append(Paragraph(
        "<b>Primary:</b> Acute Coronary Syndrome (ACS) with Triple Vessel "
        "Coronary Artery Disease (CAD-TVD). ICD-10: I25.10",
        body_style
    ))
    elements.append(Paragraph(
        "<b>Secondary:</b><br/>"
        "• Type 2 Diabetes Mellitus, controlled (ICD-10: E11.9)<br/>"
        "• Essential Hypertension, controlled (ICD-10: I10)<br/>"
        "• Hyperlipidemia (ICD-10: E78.5)",
        body_style
    ))

    # --- Procedures Performed ---
    elements.append(Paragraph("PROCEDURES PERFORMED", section_style))
    elements.append(Paragraph(
        "<b>1. Coronary Angiography</b> (Pre-operative assessment)<br/>"
        "&nbsp;&nbsp;&nbsp;Date: 11/03/2025 | Performed by: Dr. Rajesh Mehta",
        body_style
    ))
    elements.append(Paragraph(
        "<b>2. Emergency Coronary Artery Bypass Grafting (CABG x 3 vessels)</b><br/>"
        "&nbsp;&nbsp;&nbsp;Date: 12/03/2025 | Performed by: Dr. Vikram Singh<br/>"
        "&nbsp;&nbsp;&nbsp;Grafts: LIMA-LAD, SVG-OM, SVG-PDA<br/>"
        "&nbsp;&nbsp;&nbsp;Drug-Eluting Stent (DES) was placed during the procedure.",
        body_style
    ))
    elements.append(Paragraph(
        "<b>3. Echocardiography (2D Echo with Color Doppler)</b><br/>"
        "&nbsp;&nbsp;&nbsp;Date: 12/03/2025 | LVEF: 45% post-procedure",
        body_style
    ))

    # --- Clinical Course ---
    elements.append(Paragraph("CLINICAL COURSE / HOSPITAL STAY", section_style))
    elements.append(Paragraph(
        "Patient presented to the Emergency Department on 11/03/2025 with severe "
        "central chest pain radiating to the left arm, diaphoresis, and shortness "
        "of breath. ECG revealed ST-segment elevation in leads V1-V4 suggestive of "
        "acute anterior wall myocardial infarction. Troponin-I was elevated at "
        "8.4 ng/mL. Patient was immediately admitted and taken up for emergency "
        "coronary angiography which revealed triple vessel disease with critical "
        "stenosis in LAD (95%), LCX (80%), and RCA (75%).",
        body_style
    ))
    elements.append(Paragraph(
        "Patient underwent emergency CABG x 3 vessels on 12/03/2025. The procedure "
        "was uneventful. Post-operatively, patient was shifted to the Cardiac ICU "
        "where he remained for 3 days (12/03 to 14/03) on monitoring with "
        "vasopressor support which was gradually tapered. Patient was then shifted "
        "to a private deluxe room on 15/03/2025 and remained there until discharge "
        "on 18/03/2025.",
        body_style
    ))
    elements.append(Paragraph(
        "During the post-operative period, patient was managed with intravenous "
        "Heparin (5000 IU x 12 vials over 3 days), IV Pantoprazole 40mg for stress "
        "ulcer prophylaxis, IV Paracetamol 1g for pain management, and oral "
        "Atorvastatin 40mg from POD 2 onwards. Patient tolerated medications well.",
        body_style
    ))

    # --- Discharge Medications ---
    elements.append(Paragraph("DISCHARGE MEDICATIONS", section_style))
    medications = [
        ["1.", "Tab. Aspirin 75mg", "Once daily, after dinner", "Lifelong"],
        ["2.", "Tab. Clopidogrel 75mg", "Once daily, morning", "12 months"],
        ["3.", "Tab. Atorvastatin 40mg", "Once daily, at bedtime", "Lifelong"],
        ["4.", "Tab. Metoprolol 25mg", "Twice daily", "Review at 1 month"],
        ["5.", "Tab. Pantoprazole 40mg", "Once daily, before breakfast", "1 month"],
        ["6.", "Tab. Metformin 500mg", "Twice daily, with meals", "Continue"],
    ]

    med_table = Table(medications, colWidths=[0.8*cm, 4*cm, 5.5*cm, 4.5*cm])
    med_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(med_table)

    # --- Discharge Condition ---
    elements.append(Paragraph("CONDITION AT DISCHARGE", section_style))
    elements.append(Paragraph(
        "Patient is hemodynamically stable, ambulatory, and tolerating oral feeds. "
        "Vital signs: BP 130/80 mmHg, PR 78/min, SpO2 98% on room air, afebrile. "
        "Surgical site is clean and dry with no signs of infection. Patient and "
        "family have been counselled regarding lifestyle modifications and follow-up.",
        body_style
    ))

    # --- Follow-up ---
    elements.append(Paragraph("FOLLOW-UP INSTRUCTIONS", section_style))
    elements.append(Paragraph(
        "• OPD review with Dr. Vikram Singh in 7 days (25/03/2025)<br/>"
        "• Echocardiography after 1 month<br/>"
        "• Lipid profile, HbA1c, and renal function after 3 months<br/>"
        "• Emergency contact: +91-22-2674-XXXX (24x7)",
        body_style
    ))

    elements.append(Spacer(1, 0.8*cm))
    elements.append(Paragraph(
        "_____________________________<br/>"
        "<b>Dr. Rajesh Mehta</b>, MD DM (Cardiology)<br/>"
        "Consultant Cardiologist, City Care Hospital<br/>"
        "Date: 18/03/2025",
        ParagraphStyle('Sig', parent=styles['Normal'], fontSize=9)
    ))

    doc.build(elements)
    print(f"Generated discharge summary: {output_path}")
    print(f"Patient: Ankit Sharma | Stay: 11/03/2025 - 18/03/2025 (7 days)")
    print(f"Ward breakdown: ICU 3d + Private Deluxe 4d")
    print(f"Procedures: Coronary Angiography, CABG x3, 2D Echo + DES")


if __name__ == "__main__":
    generate_discharge()