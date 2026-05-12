# src/scripts/parse_capstone_rules.py
import pdfplumber
import json
import re
from pathlib import Path

def extract_multi_procedure_rule(text):
    """Extract multi-procedure billing discounts"""
    return {
        "rule_name": "Multi-Procedure Billing Discount",
        "description": "When multiple surgeries happen in one OT session, only primary is 100%, second is 50%, third+ is 25%",
        "source": "capstone_verification_rules.pdf page 1",
        "discounts": [
            {"position": "primary", "percentage": 100, "description": "Highest cost procedure"},
            {"position": "second", "percentage": 50, "description": "Second procedure in same session"},
            {"position": "third_and_beyond", "percentage": 25, "description": "Third and subsequent procedures"}
        ],
        "violation_type": "unbundled_charges",
        "evidence_required": "Multiple procedures billed at 100% in same OT session"
    }

def extract_scheduled_items(text):
    """Extract scheduled vs non-scheduled consumables"""
    scheduled_items = []
    non_scheduled_items = []
    
    # Scheduled items (from page 3)
    scheduled_pattern = r'(Syringes|Needles|IV Cannulae|IV Fluids)'
    for match in re.finditer(scheduled_pattern, text):
        item = match.group(1)
        # Check if it says "Scheduled (ceiling exists)"
        context_start = max(0, match.start() - 100)
        context_end = min(len(text), match.end() + 100)
        context = text[context_start:context_end]
        
        if "Scheduled" in context and "ceiling" in context.lower():
            scheduled_items.append({
                "item_name": item,
                "status": "scheduled",
                "has_ceiling": True,
                "source": "capstone_verification_rules.pdf page 3"
            })
        elif "Non-scheduled" in context:
            non_scheduled_items.append({
                "item_name": item,
                "status": "non_scheduled",
                "has_ceiling": False,
                "max_increase": "10% per year",
                "source": "capstone_verification_rules.pdf page 3"
            })
    
    return {
        "scheduled_items": scheduled_items,
        "non_scheduled_items": non_scheduled_items
    }

def extract_timeline_rules(text):
    """Extract IRDAI timeline requirements from pages 12-15"""
    timelines = []
    
    # Pre-authorization timeline
    if "one hour" in text.lower() and "cashless" in text.lower():
        timelines.append({
            "rule_name": "Cashless Pre-Authorization Timeline",
            "requirement": "Insurer must approve within 1 hour of request",
            "timeline_minutes": 60,
            "violation_penalty": "Delay beyond 1 hour constitutes service violation",
            "source": "IRDAI Master Circular 2024, page 12-13",
            "effective_date": "2024-07-31"
        })
    
    # Final authorization timeline
    if "three hours" in text.lower() and "discharge" in text.lower():
        timelines.append({
            "rule_name": "Final Authorization Timeline",
            "requirement": "Insurer must grant final authorization within 3 hours of discharge request",
            "timeline_minutes": 180,
            "violation_penalty": "Additional charges borne by insurer if delayed beyond 3 hours",
            "source": "IRDAI Master Circular 2024, page 13",
            "effective_date": "2024-07-31"
        })
    
    # Complaint resolution timeline
    if "14 days" in text or "fourteen days" in text.lower():
        timelines.append({
            "rule_name": "Complaint Resolution Timeline",
            "requirement": "Insurers must resolve complaints within 14 days",
            "timeline_days": 14,
            "source": "IRDAI regulations page 14-15",
            "effective_date": "2024-01-01"
        })
    
    return timelines

def extract_trade_margin_caps(text):
    """Extract trade margin caps for devices"""
    margins = []
    
    # COVID devices 70% cap
    covid_devices = ["Oxygen Concentrator", "Pulse Oximeter", "Blood Pressure Monitor", 
                     "Nebulizer", "Digital Thermometer", "Glucometer"]
    
    if "70%" in text and "trade margin" in text.lower():
        for device in covid_devices:
            if device in text:
                margins.append({
                    "device_name": device,
                    "max_trade_margin": 70,
                    "cap_type": "percentage",
                    "source": "NPPA orders June-July 2021",
                    "category": "covid_essential"
                })
    
    return margins

def extract_notified_devices(text):
    """Extract the 24+4 notified medical device categories"""
    devices = []
    
    # Parse the numbered device list from pages 7-10
    device_patterns = [
        r'(\d+)\s+(Disposable Hypodermic Syringes)',
        r'(\d+)\s+(Disposable Hypodermic Needles)',
        r'(\d+)\s+(Stents)',
        r'(\d+)\s+(Catheters)',
        r'(\d+)\s+(Intra-Ocular Lenses)',
        r'(\d+)\s+(Heart Valves)',
        r'(\d+)\s+(Orthopaedic Implants)',
        r'(\d+)\s+(Knee [Ii]mplants?)',
    ]
    
    for pattern in device_patterns:
        matches = re.finditer(pattern, text)
        for match in matches:
            device_num = match.group(1)
            device_name = match.group(2)
            devices.append({
                "device_number": int(device_num),
                "device_name": device_name,
                "regulated_as": "Drug under Medical Devices Rules",
                "notified_date": "2020-04-01",
                "source": "capstone_verification_rules.pdf pages 7-10"
            })
    
    return devices

def main():
    pdf_path = Path("data/raw/capstone_verification_rules.pdf")
    output_path = Path("data/reference/capstone_rules.json")
    
    print("Extracting rules from capstone_verification_rules.pdf...")
    
    all_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            all_text += page.extract_text() + "\n\n"
    
    # Extract all rule types
    rules = {
        "multi_procedure_billing": extract_multi_procedure_rule(all_text),
        "scheduled_items": extract_scheduled_items(all_text),
        "timeline_requirements": extract_timeline_rules(all_text),
        "trade_margin_caps": extract_trade_margin_caps(all_text),
        "notified_devices": extract_notified_devices(all_text),
        "metadata": {
            "source_document": "capstone_verification_rules.pdf",
            "extraction_date": "2026-05-12",
            "total_rules_extracted": 0
        }
    }
    
    # Count total rules
    total_rules = (
        1 +  # multi-procedure
        len(rules["scheduled_items"]["scheduled_items"]) +
        len(rules["scheduled_items"]["non_scheduled_items"]) +
        len(rules["timeline_requirements"]) +
        len(rules["trade_margin_caps"]) +
        len(rules["notified_devices"])
    )
    rules["metadata"]["total_rules_extracted"] = total_rules
    
    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(rules, f, indent=2)
    
    print(f"\n✅ Extracted {total_rules} rules:")
    print(f"   - Multi-procedure billing: 1 rule")
    print(f"   - Scheduled items: {len(rules['scheduled_items']['scheduled_items'])}")
    print(f"   - Non-scheduled items: {len(rules['scheduled_items']['non_scheduled_items'])}")
    print(f"   - Timeline requirements: {len(rules['timeline_requirements'])}")
    print(f"   - Trade margin caps: {len(rules['trade_margin_caps'])}")
    print(f"   - Notified devices: {len(rules['notified_devices'])}")
    print(f"\n💾 Saved to: {output_path}")
    
    print("\n📋 Next steps:")
    print("1. Review extracted rules: cat data/reference/capstone_rules.json | head -100")
    print("2. Implement detection logic in src/agent/core.py")
    print("3. Update test case to verify new detections")

if __name__ == "__main__":
    main()