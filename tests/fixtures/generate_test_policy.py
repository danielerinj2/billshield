"""
Generate a synthetic insurance policy PDF for testing.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from pathlib import Path

def generate_test_policy():
    """Generate a realistic test insurance policy PDF."""
    
    output_path = "data/samples/test_policy.pdf"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    doc = SimpleDocTemplate(output_path, pagesize=A4)
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor='darkblue',
        spaceAfter=12,
        alignment=TA_CENTER
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=12,
        textColor='darkblue',
        spaceAfter=6,
        spaceBefore=12
    )
    
    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['BodyText'],
        fontSize=10,
        alignment=TA_JUSTIFY,
        spaceAfter=6
    )
    
    story = []
    
    # Title
    story.append(Paragraph("HEALTH INSURANCE POLICY", title_style))
    story.append(Paragraph("Policy Number: HLTH/2025/123456", styles['Normal']))
    story.append(Spacer(1, 0.3*inch))
    
    # Section 1: Coverage
    story.append(Paragraph("1. COVERAGE", heading_style))
    story.append(Paragraph(
        "This policy provides coverage for hospitalization expenses up to the Sum Insured of "
        "<b>₹5,00,000</b> per policy year. Coverage includes room rent, ICU charges, "
        "surgery costs, medicines, and diagnostic tests.",
        body_style
    ))
    story.append(Paragraph(
        "Pre-hospitalization expenses are covered for <b>60 days</b> before admission and "
        "post-hospitalization expenses for <b>90 days</b> after discharge.",
        body_style
    ))
    
    # Section 2: Sub-limits
    story.append(Paragraph("2. SUB-LIMITS", heading_style))
    story.append(Paragraph(
        "(a) <b>Room Rent:</b> Maximum ₹5,000 per day for general ward. "
        "ICU charges capped at ₹10,000 per day.",
        body_style
    ))
    story.append(Paragraph(
        "(b) <b>Ambulance:</b> Maximum ₹2,000 per hospitalization.",
        body_style
    ))
    story.append(Paragraph(
        "(c) <b>Cataract Surgery:</b> Maximum ₹40,000 per eye per policy year.",
        body_style
    ))
    
    # Section 3: Exclusions
    story.append(Paragraph("3. EXCLUSIONS", heading_style))
    story.append(Paragraph(
        "The following are NOT covered under this policy:",
        body_style
    ))
    story.append(Paragraph(
        "(i) Dental treatment unless requiring hospitalization exceeding 24 hours.",
        body_style
    ))
    story.append(Paragraph(
        "(ii) Cosmetic or plastic surgery except for medically necessary reconstructive surgery.",
        body_style
    ))
    story.append(Paragraph(
        "(iii) Treatment for obesity, weight control, or bariatric surgery.",
        body_style
    ))
    story.append(Paragraph(
        "(iv) Expenses incurred at non-network hospitals without prior cashless authorization "
        "(reimbursement may be limited to 80% of eligible amount).",
        body_style
    ))
    story.append(Paragraph(
        "(v) Items of personal comfort including but not limited to: telephone charges, "
        "attendant charges, television, barber services, cosmetics, diapers.",
        body_style
    ))
    
    story.append(PageBreak())
    
    # Section 4: Waiting Periods
    story.append(Paragraph("4. WAITING PERIODS", heading_style))
    story.append(Paragraph(
        "(a) <b>Initial Waiting Period:</b> 30 days from policy inception for all claims except "
        "accident-related hospitalization.",
        body_style
    ))
    story.append(Paragraph(
        "(b) <b>Pre-existing Diseases:</b> 48 months waiting period for conditions existing prior "
        "to policy purchase.",
        body_style
    ))
    story.append(Paragraph(
        "(c) <b>Specific Diseases:</b> 24 months for cataract, hernia, hysterectomy, "
        "joint replacement surgery, benign prostatic hypertrophy, and gallbladder stones.",
        body_style
    ))
    
    # Section 5: Co-payment
    story.append(Paragraph("5. CO-PAYMENT", heading_style))
    story.append(Paragraph(
        "For policyholders aged 60 years and above, a co-payment of <b>20%</b> applies to all claims. "
        "This means the insured bears 20% of admissible claim amount, and the company pays 80%.",
        body_style
    ))
    
    # Section 6: Claim Procedure
    story.append(Paragraph("6. CLAIM PROCEDURE", heading_style))
    story.append(Paragraph(
        "(a) <b>Cashless Claims:</b> Contact our 24x7 helpline at 1800-XXX-XXXX at least "
        "24 hours before planned hospitalization. For emergency admissions, notify within "
        "24 hours of admission.",
        body_style
    ))
    story.append(Paragraph(
        "(b) <b>Reimbursement Claims:</b> Submit claim form with original bills, discharge summary, "
        "diagnostic reports, and payment receipts within 15 days of discharge.",
        body_style
    ))
    story.append(Paragraph(
        "(c) All claims are subject to medical review and verification of supporting documents.",
        body_style
    ))
    
    # Build PDF
    doc.build(story)
    print(f"✅ Generated test policy: {output_path}")
    return output_path

if __name__ == "__main__":
    generate_test_policy()