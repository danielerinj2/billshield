"""
Generate a synthetic hospital bill PDF for testing BillShield.

Models Ankit's scenario from the capstone:
- 45M, emergency CABG, Mumbai (Tier X)
- ~₹6L total with embedded overcharges
- 20+ specific issues the agent should detect

Output: data/samples/test_bill_ankit.pdf

This file lives in tests/fixtures/ because it generates test data,
not production code. Run from project root with:
    python -m tests.fixtures.generate_test_bill
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


# Bill line items with embedded issues for testing
# Format: (date, description, qty, rate, amount, test_note)
LINE_ITEMS = [
    # --- Procedure charges (CGHS-verifiable) ---
    ("12/03/2025", "CABG - Coronary Artery Bypass Grafting (3 vessels)", 1, 285000, 285000,
     "CGHS CP004 X-tier rate is ~Rs 1,50,000. This is ~90% above CGHS."),

    ("12/03/2025", "Echocardiography - 2D Echo with Color Doppler", 1, 8500, 8500,
     "CGHS CC026 X-tier rate is Rs 1,500. ~5.6x overcharge."),

    ("11/03/2025", "ECG - 12 Lead", 2, 1200, 2400,
     "CGHS CC024 X-tier rate is Rs 100/test. ~12x overcharge."),

    ("12/03/2025", "Coronary Angiography (Pre-op assessment)", 1, 45000, 45000,
     "Multi-procedure rule violation - secondary procedure billed at 100% (should be 50%)."),

    # --- ICU charges ---
    ("12/03 - 14/03", "ICU Stay (3 days @ Rs 22,000/day)", 3, 22000, 66000,
     "CGHS ICU rate X-tier is ~Rs 7,500/day. ~3x overcharge."),

    ("12/03 - 14/03", "ICU Monitoring & Nursing Charges", 3, 5000, 15000,
     "Likely bundled into ICU rate per CGHS - separate billing questionable."),

    # --- Ward charges ---
    ("15/03 - 18/03", "Private Room (Deluxe Category) - 4 days", 4, 8500, 34000,
     "Likely above policy room rent cap - proportional deduction trigger."),

    # --- Drug charges (NPPA-verifiable) ---
    ("12/03/2025", "Inj. Heparin 5000 IU - 12 vials", 12, 450, 5400,
     "NPPA ceiling for Heparin is approx Rs 180/vial. ~2.5x above ceiling."),

    ("12/03 - 18/03", "Tab. Atorvastatin 40mg - 14 tabs", 14, 85, 1190,
     "NPPA ceiling approx Rs 12/tab. ~7x above ceiling."),

    ("12/03 - 18/03", "Inj. Pantoprazole 40mg IV - 8 vials", 8, 320, 2560,
     "NPPA ceiling approx Rs 95/vial. ~3.4x above ceiling."),

    ("12/03/2025", "Inj. Paracetamol 1g IV - 6 vials", 6, 280, 1680,
     "NPPA ceiling approx Rs 35/vial. ~8x above ceiling."),

    # --- Device charges ---
    ("12/03/2025", "Drug-Eluting Stent (DES) - Cardiology consumable", 1, 65000, 65000,
     "NPPA ceiling for DES is Rs 39,186.03 + GST. ~50% above ceiling."),

    # --- Diagnostic charges ---
    ("11/03/2025", "Complete Blood Count (CBC)", 1, 850, 850,
     "CGHS rate X-tier is Rs 150. ~5.6x overcharge."),

    ("11/03/2025", "Lipid Profile", 1, 1800, 1800,
     "CGHS rate X-tier is Rs 250. ~7x overcharge."),

    ("11/03/2025", "Troponin-I (Cardiac marker)", 2, 1500, 3000,
     "CGHS rate X-tier is Rs 450/test. ~3.3x overcharge."),

    ("11/03/2025", "Chest X-Ray (PA view)", 1, 1200, 1200,
     "CGHS rate X-tier is Rs 140. ~8.5x overcharge."),

    # --- Non-payable items (IRDAI list) ---
    ("12/03/2025", "Toiletries & Personal Care Items", 1, 1200, 1200,
     "IRDAI non-payable item #1-15. Should not be billed to insurer."),

    ("12/03/2025", "Telephone & Internet Charges", 1, 800, 800,
     "IRDAI non-payable item #29, #39."),

    ("12/03/2025", "Attendant Food Charges (Non-patient)", 1, 2400, 2400,
     "IRDAI non-payable item #30."),

    ("12/03/2025", "Documentation & Admin Charges", 1, 1500, 1500,
     "IRDAI non-payable item #73."),

    # --- Service & misc charges ---
    ("18/03/2025", "Discharge & Documentation Charges", 1, 2500, 2500,
     "Generic service charge - verify against IRDAI list."),

    ("11/03 - 18/03", "Visiting Consultant Charges (Cardiologist)", 7, 2000, 14000,
     "Daily consultant visits - verify CGHS limits."),

    ("12/03/2025", "OT Charges - Operating Theatre", 1, 25000, 25000,
     "Likely bundled into CABG package per CGHS - separate billing flagged."),

    ("12/03/2025", "Anaesthesia Charges (Independent)", 1, 18000, 18000,
     "Likely bundled into CABG package per CGHS - separate billing flagged."),
]


def generate_bill():
    """Generate the synthetic test bill PDF."""
    # Resolve output path relative to project root
    project_root = Path(__file__).parent.parent.parent
    output_path = project_root / "data" / "samples" / "test_bill_ankit.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=1.5*cm,
        leftMargin=1.5*cm,
        topMargin=1.5*cm,
        bottomMargin=1.5*cm,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=16,
        spaceAfter=6,
        alignment=1,
    )

    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        alignment=1,
        spaceAfter=12,
    )

    elements = []

    # Hospital header
    elements.append(Paragraph("CITY CARE HOSPITAL", title_style))
    elements.append(Paragraph(
        "123 Health Boulevard, Andheri West, Mumbai - 400058<br/>"
        "NABH Accredited | Tel: +91-22-2674-XXXX | Email: billing@citycare.example",
        subtitle_style
    ))
    elements.append(Spacer(1, 0.3*cm))

    # Bill metadata
    bill_meta = [
        ["Bill Number:", "CCH/2025/03/4821", "Bill Date:", "18/03/2025"],
        ["Patient Name:", "Ankit Sharma", "Age/Sex:", "45 Years / Male"],
        ["Patient ID:", "CCH-IP-2025-1247", "Ward Type:", "Private (Deluxe)"],
        ["Admission Date:", "11/03/2025", "Discharge Date:", "18/03/2025"],
        ["Diagnosis:", "Acute Coronary Syndrome (ACS), Triple Vessel Disease", "", ""],
        ["Procedure:", "Emergency CABG x3 (LIMA-LAD, SVG-OM, SVG-PDA)", "", ""],
        ["Consultant:", "Dr. Rajesh Mehta, MD DM (Cardiology)", "", ""],
        ["Insurance:", "Star Health Insurance - Policy: SH-2024-887234", "", ""],
    ]

    meta_table = Table(bill_meta, colWidths=[3.5*cm, 5.5*cm, 3.5*cm, 4.5*cm])
    meta_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 0.5*cm))

    elements.append(Paragraph(
        "<b>ITEMIZED CHARGES</b>",
        ParagraphStyle('SectionHeader', parent=styles['Normal'], fontSize=11, spaceAfter=6)
    ))

    # Line items table
    table_data = [["Date", "Description", "Qty", "Rate", "Amount"]]
    subtotal = 0
    for date, desc, qty, rate, amount, _ in LINE_ITEMS:
        rate_str = f"{rate:,}" if rate else ""
        amount_str = f"{amount:,}"
        qty_str = str(qty) if qty else ""
        table_data.append([date, desc, qty_str, rate_str, amount_str])
        subtotal += amount

    gst = round(subtotal * 0.05, 2)
    grand_total = subtotal + gst

    table_data.append(["", "", "", "Sub Total:", f"{subtotal:,}"])
    table_data.append(["", "", "", "GST (5%):", f"{gst:,.2f}"])
    table_data.append(["", "", "", "GRAND TOTAL:", f"{grand_total:,.2f}"])

    items_table = Table(
        table_data,
        colWidths=[2.5*cm, 8*cm, 1.2*cm, 2.5*cm, 2.8*cm],
        repeatRows=1,
    )

    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2C3E50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),

        ('FONTNAME', (0, 1), (-1, -4), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (2, 1), (4, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ('TOPPADDING', (0, 1), (-1, -1), 4),

        ('ROWBACKGROUNDS', (0, 1), (-1, -4), [colors.white, colors.HexColor('#F5F5F5')]),

        ('FONTNAME', (3, -3), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (3, -1), (-1, -1), 10),
        ('LINEABOVE', (3, -3), (-1, -3), 1, colors.black),
        ('LINEABOVE', (3, -1), (-1, -1), 1.5, colors.black),

        ('GRID', (0, 0), (-1, -4), 0.25, colors.grey),
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.black),
    ]))

    elements.append(items_table)

    elements.append(Spacer(1, 0.5*cm))
    elements.append(Paragraph(
        "<b>Payment Terms:</b> Payment due at discharge. "
        "Insurance claim should be settled at the time of discharge.",
        ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8,
                       textColor=colors.grey, spaceBefore=12)
    ))

    elements.append(Paragraph(
        "<b>Authorized Signatory</b><br/><br/>"
        "_________________________<br/>"
        "Billing Manager, City Care Hospital",
        ParagraphStyle('Sig', parent=styles['Normal'], fontSize=9, spaceBefore=20)
    ))

    doc.build(elements)

    print(f"Generated synthetic bill: {output_path}")
    print(f"Total line items: {len(LINE_ITEMS)}")
    print(f"Subtotal: Rs {subtotal:,}")
    print(f"GST (5%): Rs {gst:,.2f}")
    print(f"Grand Total: Rs {grand_total:,.2f}")
    print()
    print("Embedded test issues (for agent to detect):")
    for i, item in enumerate(LINE_ITEMS, 1):
        if item[5]:
            print(f"  {i:>2}. {item[1][:45]:<45} | {item[5][:60]}")


if __name__ == "__main__":
    generate_bill()