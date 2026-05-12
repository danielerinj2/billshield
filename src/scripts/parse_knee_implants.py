# src/scripts/parse_knee_implants.py
import pdfplumber
import json
import re
from pathlib import Path

def parse_knee_implant_table(pdf_path):
    """Parse the knee implant price table from NPPA PDF"""
    devices = []
    
    with pdfplumber.open(pdf_path) as pdf:
        text = pdf.pages[0].extract_text()
        
        # Extract prices from the structured table
        # FEMUR components
        femur_prices = {
            'Titanium': re.search(r'Titanium\s+(\d+)', text),
            'Oxidized Zirconium': re.search(r'Oxidized Zirconium\s+(\d+)', text),
            'Hi flex': re.search(r'Hi flex\s+(\d+)', text),
            'Co Cr': re.search(r'Co Cr\s+(\d+)', text.replace('Co Cr 26499', 'CoCr 26499'))  # Handle femur Co Cr
        }
        
        # TIBIA components
        tibia_prices = {
            'Titanium': re.search(r'TIBIA.*?Titanium\s+(\d+)', text, re.DOTALL),
            'Co Cr': re.search(r'TIBIA.*?Co Cr\s+(\d+)', text, re.DOTALL)
        }
        
        # Other components
        insert_match = re.search(r'INSERT.*?(\d+)', text)
        patella_match = re.search(r'PATELLA.*?(\d+)', text)
        monoblock_poly_match = re.search(r'All Poly\s+(\d+)', text)
        monoblock_metallic_match = re.search(r'Metallic tibia.*?(\d+)', text)
        
        # Revision components
        revision_femur_match = re.search(r'REVISION.*?FEMUR.*?(\d+)', text, re.DOTALL)
        revision_tibia_match = re.search(r'REVISION.*?TIBIA.*?(\d+)', text, re.DOTALL)
        
        # Create device entries for primary components (most common configurations)
        
        # 1. Total Knee Replacement (highest femur + tibia + insert + patella)
        max_femur = max([int(m.group(1)) for m in femur_prices.values() if m], default=0)
        max_tibia = max([int(m.group(1)) for m in tibia_prices.values() if m], default=0)
        insert_price = int(insert_match.group(1)) if insert_match else 0
        patella_price = int(patella_match.group(1)) if patella_match else 0
        
        total_tkr_price = max_femur + max_tibia + insert_price + patella_price
        
        if total_tkr_price > 0:
            devices.append({
                "device_name": "Total Knee Replacement (Complete)",
                "specifications": "Femur + Tibia + Insert + Patella (highest grade components)",
                "ceiling_price_inr": total_tkr_price,
                "category": "orthopedic_implant",
                "nppa_notification": "NPPA Knee Implant Price Cap 2025",
                "source": "nppa_devices_knee_implants_2025.pdf",
                "components": {
                    "femur": max_femur,
                    "tibia": max_tibia,
                    "insert": insert_price,
                    "patella": patella_price
                }
            })
        
        # 2. Individual high-value components (for partial replacements)
        if max_femur > 0:
            devices.append({
                "device_name": "Knee Implant - Femur Component",
                "specifications": "Femoral component (Titanium/Oxidized Zirconium)",
                "ceiling_price_inr": max_femur,
                "category": "orthopedic_implant",
                "nppa_notification": "NPPA Knee Implant Price Cap 2025",
                "source": "nppa_devices_knee_implants_2025.pdf"
            })
        
        if max_tibia > 0:
            devices.append({
                "device_name": "Knee Implant - Tibia Component",
                "specifications": "Tibial component (Titanium/Co-Cr)",
                "ceiling_price_inr": max_tibia,
                "category": "orthopedic_implant",
                "nppa_notification": "NPPA Knee Implant Price Cap 2025",
                "source": "nppa_devices_knee_implants_2025.pdf"
            })
        
        # 3. Revision components (for re-operations)
        if revision_femur_match:
            devices.append({
                "device_name": "Knee Implant - Revision Femur",
                "specifications": "Revision femoral component",
                "ceiling_price_inr": int(revision_femur_match.group(1)),
                "category": "orthopedic_implant",
                "nppa_notification": "NPPA Knee Implant Price Cap 2025",
                "source": "nppa_devices_knee_implants_2025.pdf"
            })
        
        if revision_tibia_match:
            devices.append({
                "device_name": "Knee Implant - Revision Tibia",
                "specifications": "Revision tibial component",
                "ceiling_price_inr": int(revision_tibia_match.group(1)),
                "category": "orthopedic_implant",
                "nppa_notification": "NPPA Knee Implant Price Cap 2025",
                "source": "nppa_devices_knee_implants_2025.pdf"
            })
    
    return devices

def main():
    knee_pdf = Path("data/raw/nppa_devices_knee_implants_2025.pdf")
    devices_json = Path("data/reference/nppa_devices.json")
    
    # Load existing devices (stents from capstone doc)
    with open(devices_json, 'r') as f:
        existing_devices = json.load(f)
    
    print(f"Current devices in nppa_devices.json: {len(existing_devices)}")
    for d in existing_devices:
        print(f"  - {d['device_name']}: ₹{d['ceiling_price_inr']:,}")
    
    # Parse knee implants
    print(f"\nParsing {knee_pdf}...")
    knee_devices = parse_knee_implant_table(knee_pdf)
    
    print(f"\nFound {len(knee_devices)} knee implant entries:")
    for d in knee_devices:
        print(f"  - {d['device_name']}: ₹{d['ceiling_price_inr']:,}")
    
    # Merge and save
    all_devices = existing_devices + knee_devices
    with open(devices_json, 'w') as f:
        json.dump(all_devices, f, indent=2)
    
    print(f"\n✅ Saved {len(all_devices)} total devices to {devices_json}")
    print(f"\nNext: Reload ChromaDB")
    print(f"  python src/rag/load_to_chromadb.py")

if __name__ == "__main__":
    main()