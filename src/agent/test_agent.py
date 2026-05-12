"""
Integration test: Run agent on synthetic test data.
"""
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.core import BillShieldAgent
from rag.retrieval import BillShieldRAG


def load_test_data():
    """Load parsed test documents."""
    bill_path = "data/uploaded/test_bill_ankit_parsed.json"
    discharge_path = "data/uploaded/test_discharge_ankit_parsed.json"
    rejection_path = "data/uploaded/test_rejection_ankit_parsed.json"

    with open(bill_path, 'r') as f:
        bill_data = json.load(f)

    with open(discharge_path, 'r') as f:
        discharge_data = json.load(f)

    with open(rejection_path, 'r') as f:
        rejection_data = json.load(f)

    return bill_data, discharge_data, rejection_data


def test_agent():
    """Run agent on test data."""
    print("="*70)
    print("BillShield Agent Integration Test")
    print("="*70)

    # Load test data
    print("\n1. Loading test documents...")
    bill_data, discharge_data, rejection_data = load_test_data()

    bill_total = bill_data["totals"]["extracted_grand_total"]
    rejection_total = rejection_data["financial_summary"]["amount_rejected"]

    print(f"   ✅ Bill: ₹{bill_total:,.0f} total")
    print(f"   ✅ Discharge: {len(discharge_data['procedures'])} procedures")
    print(f"   ✅ Rejection: ₹{rejection_total:,.0f} rejected")

    # Initialize RAG
    print("\n2. Initializing RAG system...")
    rag = BillShieldRAG(chromadb_path="data/chromadb")
    print(f"   ✅ IRDAI collection: {rag.irdai_collection.count()} chunks")
    print(f"   ✅ Reference collection: {rag.reference_collection.count()} items")

    # Initialize agent
    print("\n3. Initializing agent...")
    agent = BillShieldAgent(rag_system=rag)
    print("   ✅ Agent ready")

    # Run analysis
    print("\n4. Running analysis...")
    result = agent.analyze(
        bill_data=bill_data,
        discharge_data=discharge_data,
        rejection_data=rejection_data,
        policy_available=True
    )

    # Display results
    print("\n" + "="*70)
    print("ANALYSIS RESULTS")
    print("="*70)

    print(f"\n💰 Financial Summary:")
    print(f"   Total Bill:          ₹{result.total_bill:>12,.0f}")
    print(f"   Insurer Approved:    ₹{result.total_approved:>12,.0f}")
    print(f"   Insurer Rejected:    ₹{result.total_rejected:>12,.0f}")
    print(f"   Patient Liability:   ₹{result.total_patient_liability:>12,.0f}")
    print(f"   Verified Overcharge: ₹{result.total_verified_overcharge:>12,.0f}")

    print(f"\n📊 Estimated Recoverable:")
    print(f"   Minimum (High Confidence): ₹{result.estimated_recoverable['min']:,.0f}")
    print(f"   Maximum (Inc. Medium):     ₹{result.estimated_recoverable['max']:,.0f}")

    print(f"\n🚩 Issues Found: {len(result.issues)}")

    # Show top 5 issues
    sorted_issues = sorted(
        result.issues,
        key=lambda x: x.overcharge_amount or 0,
        reverse=True
    )

    for i, issue in enumerate(sorted_issues[:5], 1):
        print(f"\n   Issue #{i}: {issue.issue_id}")
        print(f"   Type: {issue.issue_type.value}")
        print(f"   Confidence: {issue.confidence.value.upper()}")
        print(f"   Description: {issue.description}")
        if issue.overcharge_amount:
            print(f"   Overcharge: ₹{issue.overcharge_amount:,.0f}")
        print(f"   Evidence: {issue.evidence[0]}")
        print(f"   Action: {issue.action_required}")

    if len(sorted_issues) > 5:
        print(f"\n   ... and {len(sorted_issues) - 5} more issues")

    print(f"\n📋 Summary:")
    print(f"   {result.summary}")

    print(f"\n✅ Recommendations:")
    for i, rec in enumerate(result.recommendations, 1):
        print(f"   {i}. {rec}")

    # Save result
    output_path = "data/uploaded/test_analysis_result.json"
    with open(output_path, 'w') as f:
        json.dump(result.to_dict(), f, indent=2)

    print(f"\n💾 Full analysis saved to: {output_path}")

    print("\n" + "="*70)
    print("✅ Integration test complete!")
    print("="*70)


if __name__ == "__main__":
    test_agent()