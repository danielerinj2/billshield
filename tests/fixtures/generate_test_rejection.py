"""
Generate a synthetic insurance rejection letter PDF for testing BillShield.

Models Ankit's scenario:
- Star Health Insurance partial rejection
- Claimed: Rs 4,87,000 | Settled: Rs 2,94,000 | Disputed: Rs 1,93,000
- Specific line-item rejections with policy clause citations

Output: data/samples/test_rejection_ankit.pdf

Run from project root:
    python -m tests.fixtures.generate_test_rejection
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


# Rejection line items: (description, amount_claimed, amount_settled, status, clause, reason)
REJECTED_ITEMS = [
    ("CABG - Coronary Artery Bypass Grafting", 285000, 175000,
     "PARTIALLY APPROVED", "Clause 5.2.3",
     "Procedure cost capped at hospital network rate"),

    ("Drug-Eluting Stent (DES)", 65000, 39186,
     "PARTIALLY APPROVED", "Clause 6.1 (Implants)",
     "NPPA ceiling rate applied per policy"),

    ("ICU Stay (3 days)", 66000, 22500,
     "PARTIALLY APPROVED", "Clause 4.5",
     "ICU charges capped at Rs 7,500/day per policy"),

    ("Private Room Charges (Deluxe, 4 days)", 34000, 16000,
     "PARTIALLY APPROVED", "Clause 4.3",
     "Room rent capped at 1% of sum insured (Rs 4,000/day)"),

    ("ICU Monitoring & Nursing Charges", 15000, 0,
     "REJECTED", "Clause 7.2",
     "Bundled in ICU rate; cannot be billed separately"),

    ("OT Charges (Operating Theatre)", 25000, 0,
     "REJECTED", "Clause 7.2",
     "Bundled in surgical procedure rate; cannot be billed separately"),

    ("Anaesthesia Charges (Independent)", 18000, 0,
     "REJECTED", "Clause 7.2",
     "Bundled in surgical procedure rate; cannot be billed separately"),

    ("Toiletries & Personal Care Items", 1200, 0,
     "REJECTED", "Annexure-I (Non-Payable)",
     "Listed in IRDAI Standard Non-Payable Items"),

    ("Telephone & Internet Charges", 800, 0,
     "REJECTED", "Annexure-I (Non-Payable)",
     "Listed in IRDAI Standard Non-Payable Items"),

    ("Attendant Food Charges", 2400, 0,
     "REJECTED", "Annexure-I (Non-Payable)",
     "Listed in IRDAI Standard Non-Payable Items"),

    ("Documentation & Admin Charges", 1500, 0,
     "REJECTED", "Annexure-I (Non-Payable)",
     "Listed in IRDAI Standard Non-Payable Items"),

    ("Visiting Consultant Charges", 14000, 5600,
     "PARTIALLY APPROVED", "Clause 4.7",
     "Consultant fees capped at Rs 800/visit"),
]


def generate_rejection():
    project_root = Path(__file__).parent.parent.parent
    output_path = project_root / "data" / "samples" / "test_rejection_ankit.pdf"
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
        fontSize=14, spaceAfter=4, alignment=1,
    )
    subtitle_style = ParagraphStyle(
        'Subtitle', parent=styles['Normal'],
        fontSize=9, alignment=1, spaceAfter=8, textColor=colors.grey,
    )
    section_style = ParagraphStyle(
        'Section', parent=styles['Normal'],
        fontSize=11, spaceBefore=12, spaceAfter=6,
        textColor=colors.HexColor('#8B0000'),
        fontName='Helvetica-Bold',
    )
    body_style = ParagraphStyle(
        'Body', parent=styles['Normal'],
        fontSize=10, spaceAfter=6, leading=14,
    )

    elements = []

    # --- Insurer Header ---
    elements.append(Paragraph("STAR HEALTH INSURANCE CO. LTD.", title_style))
    elements.append(Paragraph(
        "Corporate Office: 1, New Tank Street, Valluvar Kottam High Road, "
        "Nungambakkam, Chennai - 600034<br/>"
        "IRDAI Registration No: 129 | CIN: U66010TN2005PLC056649",
        subtitle_style
    ))
    elements.append(Spacer(1, 0.3*cm))

    elements.append(Paragraph(
        "<b>CLAIM SETTLEMENT &amp; PARTIAL REJECTION INTIMATION</b>",
        ParagraphStyle('DocTitle', parent=styles['Normal'], fontSize=12,
                       alignment=1, spaceAfter=14)
    ))

    # --- Claim Metadata ---
    claim_meta = [
        ["Claim Number:", "STAR/2025/CLM/00887234", "Date of Letter:", "20/03/2025"],
        ["Policy Number:", "SH-2024-887234", "Policy Holder:", "Ankit Sharma"],
        ["Insured Name:", "Ankit Sharma", "Sum Insured:", "Rs 4,00,000"],
        ["Hospital:", "City Care Hospital, Mumbai", "Cashless:", "Yes"],
        ["Admission Date:", "11/03/2025", "Discharge Date:", "18/03/2025"],
        ["Pre-Auth Date:", "11/03/2025", "Pre-Auth Status:", "Approved (Rs 3,50,000)"],
        ["Date of Rejection:", "19/03/2025", "Response Time:", "1 day post-discharge"],
    ]

    claim_table = Table(claim_meta, colWidths=[3.5*cm, 5*cm, 3.5*cm, 5*cm])
    claim_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(claim_table)

    # --- Addressee ---
    elements.append(Spacer(1, 0.4*cm))
    elements.append(Paragraph(
        "<b>To:</b><br/>"
        "Mr. Ankit Sharma<br/>"
        "Policy: SH-2024-887234<br/>"
        "Hospital: City Care Hospital, Mumbai",
        body_style
    ))

    # --- Opening ---
    elements.append(Paragraph("Dear Policyholder,", body_style))
    elements.append(Paragraph(
        "We refer to your claim submitted under the above policy in connection with "
        "your hospitalization at City Care Hospital, Mumbai, from 11/03/2025 to "
        "18/03/2025 for Emergency Coronary Artery Bypass Grafting (CABG). "
        "After review of the submitted documents, we have settled your claim as detailed below.",
        body_style
    ))

    # --- Financial Summary ---
    elements.append(Paragraph("CLAIM FINANCIAL SUMMARY", section_style))

    financial_summary = [
        ["Particulars", "Amount (Rs)"],
        ["Total Amount Claimed by Hospital", "4,87,000"],
        ["Amount Approved & Settled", "2,94,000"],
        ["Amount Rejected / Patient Liability", "1,93,000"],
        ["Settlement Mode", "Cashless (direct to hospital)"],
    ]

    fin_table = Table(financial_summary, colWidths=[10*cm, 5*cm])
    fin_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#8B0000')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(fin_table)

    # --- Itemized Rejections ---
    elements.append(Paragraph("ITEMIZED CLAIM ASSESSMENT", section_style))
    elements.append(Paragraph(
        "The following line items from the hospital bill have been assessed. "
        "Items marked 'REJECTED' or 'PARTIALLY APPROVED' are detailed with the "
        "applicable policy clause and the reason for non-payment or partial payment.",
        body_style
    ))

    rejection_table_data = [
        ["Bill Item", "Claimed (Rs)", "Settled (Rs)", "Status", "Clause", "Reason"]
    ]

    for desc, claimed, settled, status, clause, reason in REJECTED_ITEMS:
        rejection_table_data.append([
            desc, f"{claimed:,}", f"{settled:,}", status, clause, reason
        ])

    rej_table = Table(
        rejection_table_data,
        colWidths=[4*cm, 1.8*cm, 1.8*cm, 2.5*cm, 2.2*cm, 5*cm],
        repeatRows=1,
    )
    rej_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2C3E50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
        ('ALIGN', (1, 0), (2, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F5F5')]),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(rej_table)

    # --- Grievance Procedure ---
    elements.append(Paragraph("GRIEVANCE REDRESSAL PROCEDURE", section_style))
    elements.append(Paragraph(
        "If you disagree with the assessment above, you may approach our Grievance "
        "Redressal Cell within 15 days of receipt of this letter. The grievance must "
        "be submitted in writing along with supporting documents.",
        body_style
    ))
    elements.append(Paragraph(
        "<b>Grievance Officer:</b> Mr. Ramesh Kumar<br/>"
        "<b>Email:</b> grievance@starhealth.example<br/>"
        "<b>Phone:</b> +91-44-2828-XXXX<br/>"
        "<b>Address:</b> Grievance Cell, Star Health Insurance Co. Ltd., "
        "1, New Tank Street, Nungambakkam, Chennai - 600034",
        body_style
    ))
    elements.append(Paragraph(
        "If the grievance is not resolved to your satisfaction within 14 days, you may "
        "escalate to the IRDAI Bima Bharosa portal (https://bimabharosa.irdai.gov.in) "
        "or approach the Insurance Ombudsman.",
        body_style
    ))

    # --- Closing ---
    elements.append(Spacer(1, 0.5*cm))
    elements.append(Paragraph(
        "We thank you for choosing Star Health Insurance. For any clarification, "
        "please contact our customer care at 1800-425-2255.",
        body_style
    ))

    elements.append(Spacer(1, 0.6*cm))
    elements.append(Paragraph(
        "<b>Sincerely,</b><br/><br/>"
        "_____________________________<br/>"
        "<b>Authorized Signatory</b><br/>"
        "Claims Department<br/>"
        "Star Health Insurance Co. Ltd.",
        ParagraphStyle('Sig', parent=styles['Normal'], fontSize=9)
    ))

    doc.build(elements)
    print(f"Generated rejection letter: {output_path}")
    print(f"Claim: STAR/2025/CLM/00887234 | Policy: SH-2024-887234")
    print(f"Claimed: Rs 4,87,000 | Settled: Rs 2,94,000 | Disputed: Rs 1,93,000")
    print(f"Itemized rejections: {len(REJECTED_ITEMS)}")
    print(f"  • PARTIALLY APPROVED: {sum(1 for i in REJECTED_ITEMS if i[3] == 'PARTIALLY APPROVED')}")
    print(f"  • REJECTED outright:  {sum(1 for i in REJECTED_ITEMS if i[3] == 'REJECTED')}")


if __name__ == "__main__":
    generate_rejection()