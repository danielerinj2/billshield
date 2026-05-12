"""Test adaptive letter generation - all 3 types."""

from pathlib import Path
from src.letters.generator import AdaptiveLetterGenerator
import json

# Load test analysis result
with open('data/uploaded/test_analysis_result.json', 'r') as f:
    analysis = json.load(f)

output_dir = Path('data/uploaded/generated_letters')
output_dir.mkdir(parents=True, exist_ok=True)

generator = AdaptiveLetterGenerator(analysis)

print("Generating letters...")
print()

# Hospital letters (all 3 tones)
for tone in ['polite', 'professional', 'firm']:
    letter = generator.generate_hospital_letter(
        tone=tone,
        patient_name="Ankit Kumar",
        hospital_name="Apollo Hospital",
        bill_number="BILL-2024-001"
    )
    
    output_file = output_dir / f'hospital_letter_{tone}.txt'
    output_file.write_text(letter)
    print(f"✅ Hospital letter ({tone}): {output_file}")

# Insurer letter (firm tone recommended)
insurer_letter = generator.generate_insurer_letter(
    tone='firm',
    patient_name="Ankit Kumar",
    insurer_name="Star Health Insurance",
    policy_number="POL-2024-12345",
    claim_number="CLM-2024-67890"
)
(output_dir / 'insurer_escalation_letter.txt').write_text(insurer_letter)
print(f"✅ Insurer escalation letter: {output_dir / 'insurer_escalation_letter.txt'}")

# Patient summary
patient_summary = generator.generate_patient_summary(
    patient_name="Ankit Kumar"
)
(output_dir / 'patient_summary.txt').write_text(patient_summary)
print(f"✅ Patient summary: {output_dir / 'patient_summary.txt'}")

print()
print("=" * 60)
print("✅ ALL LETTERS GENERATED")
print("=" * 60)
print(f"Location: {output_dir}")
print()
print("Files created:")
print("  - hospital_letter_polite.txt")
print("  - hospital_letter_professional.txt")
print("  - hospital_letter_firm.txt")
print("  - insurer_escalation_letter.txt")
print("  - patient_summary.txt")