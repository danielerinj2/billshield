# src/scripts/parse_device_prices.py
import pdfplumber
import json
import re
from pathlib import Path

def extract_capstone_devices(pdf_path):
    """Extract device prices from capstone_verification_rules.pdf"""
    devices = []
    
    with pdfplumber.open(pdf_path) as pdf:
        # Page 1 has the stent prices
        text = pdf.pages[0].extract_text()
        
        # Extract DES price: "drug-eluting stents (DES) will now cost up to Rs 39,186"
        des_match = re.search(r'drug-eluting stents.*?Rs\s*([0-9,]+)', text, re.IGNORECASE)
        if des_match:
            des_price = int(des_match.group(1).replace(',', ''))
            devices.append({
                "device_name": "Drug-Eluting Coronary Stent (DES)",
                "specifications": "Coronary stent with drug coating",
                "ceiling_price_inr": des_price,
                "category": "cardiovascular_implant",
                "nppa_notification": "NPPA Revision April 2026",
                "source": "capstone_verification_rules.pdf",
                "effective_date": "2026-04-01"
            })
        
        # Extract BMS price: "bare metal stents (BMS) are capped at Rs 10,762"
        bms_match = re.search(r'bare metal stents.*?Rs\s*([0-9,]+)', text, re.IGNORECASE)
        if bms_match:
            bms_price = int(bms_match.group(1).replace(',', ''))
            devices.append({
                "device_name": "Bare Metal Stent (BMS)",
                "specifications": "Coronary stent without drug coating",
                "ceiling_price_inr": bms_price,
                "category": "cardiovascular_implant",
                "nppa_notification": "NPPA Revision April 2026",
                "source": "capstone_verification_rules.pdf",
                "effective_date": "2026-04-01"
            })
    
    return devices

def extract_knee_implant_devices(pdf_path):
    """Extract knee implant prices from nppa_devices_knee_implants_2025.pdf"""
    devices = []
    
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            
            # Look for price patterns for knee implants
            # Common patterns: "Rs 54,720", "ceiling price of Rs X"
            price_matches = re.findall(r'(?:ceiling|price|cap).*?Rs\.?\s*([0-9,]+)', text, re.IGNORECASE)
            
            # Look for knee-related keywords
            if any(keyword in text.lower() for keyword in ['knee', 'implant', 'replacement', 'prosthesis']):
                for price_str in price_matches:
                    try:
                        price = int(price_str.replace(',', ''))
                        if 10000 <= price <= 100000:  # Reasonable range for knee implants
                            devices.append({
                                "device_name": "Knee Implant (Total Knee Replacement)",
                                "specifications": "Total knee replacement prosthesis",
                                "ceiling_price_inr": price,
                                "category": "orthopedic_implant",
                                "nppa_notification": "NPPA Order (extracted from PDF)",
                                "source": "nppa_devices_knee_implants_2025.pdf",
                                "page": page.page_number
                            })
                            break  # Take first valid price per page
                    except ValueError:
                        continue
    
    # Deduplicate by price
    seen_prices = set()
    unique_devices = []
    for device in devices:
        if device['ceiling_price_inr'] not in seen_prices:
            seen_prices.add(device['ceiling_price_inr'])
            unique_devices.append(device)
    
    return unique_devices

def main():
    # Paths
    capstone_pdf = Path("data/raw/capstone_verification_rules.pdf")
    knee_pdf = Path("data/raw/nppa_devices_knee_implants_2025.pdf")
    output_json = Path("data/reference/nppa_devices.json")
    
    all_devices = []
    
    # Extract from capstone doc
    print("Extracting device prices from capstone_verification_rules.pdf...")
    capstone_devices = extract_capstone_devices(capstone_pdf)
    print(f"  Found {len(capstone_devices)} devices:")
    for d in capstone_devices:
        print(f"    - {d['device_name']}: ₹{d['ceiling_price_inr']:,}")
    all_devices.extend(capstone_devices)
    
    # Extract from knee implant PDF
    print("\nExtracting device prices from nppa_devices_knee_implants_2025.pdf...")
    knee_devices = extract_knee_implant_devices(knee_pdf)
    print(f"  Found {len(knee_devices)} devices:")
    for d in knee_devices:
        print(f"    - {d['device_name']}: ₹{d['ceiling_price_inr']:,}")
    all_devices.extend(knee_devices)
    
    # Save to JSON
    output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json, 'w') as f:
        json.dump(all_devices, f, indent=2)
    
    print(f"\n✅ Saved {len(all_devices)} devices to {output_json}")
    print(f"\nNext steps:")
    print(f"1. Reload ChromaDB: python src/rag/load_to_chromadb.py")
    print(f"2. Re-test agent: python src/agent/test_agent.py")

if __name__ == "__main__":
    main()