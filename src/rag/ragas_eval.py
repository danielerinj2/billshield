"""
RAGAS evaluation of BillShield RAG system.
"""
import os
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    context_precision,
    context_recall,
    faithfulness,
    answer_relevancy
)
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from retrieval import BillShieldRAG

# Set OpenAI API key (RAGAS needs it for evaluation)
# If you don't have OpenAI key, we'll use a simpler eval approach
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def create_test_dataset():
    """
    Create test questions with ground truth for RAGAS evaluation.
    """
    test_cases = [
        {
            "question": "What is the timeline for cashless claim authorization?",
            "ground_truth": "Insurers must decide on cashless authorization within 1 hour of receipt of request. Final authorization for discharge must be granted within 3 hours.",
            "context_keywords": ["cashless", "authorization", "1 hour", "3 hours"]
        },
        {
            "question": "What is the claim settlement timeline for reimbursement claims?",
            "ground_truth": "Claims must be settled within 15 days from submission of all required documents.",
            "context_keywords": ["15 days", "settlement", "reimbursement"]
        },
        {
            "question": "What penalty applies if claim settlement is delayed?",
            "ground_truth": "If claims are not settled within specified timelines, the insurer must pay interest at bank rate plus 2 percent.",
            "context_keywords": ["bank rate", "2 percent", "interest", "delay"]
        },
        {
            "question": "What is the CGHS rate for ICU charges per day?",
            "ground_truth": "Neonatal ICU charges are ₹5,400 per day inclusive of incubator.",
            "context_keywords": ["ICU", "5400", "per day"]
        },
        {
            "question": "What is the grievance redressal timeline?",
            "ground_truth": "Complaints must be acknowledged immediately and resolved within 14 days.",
            "context_keywords": ["14 days", "grievance", "complaint", "resolution"]
        }
    ]

    return test_cases


def run_simple_evaluation():
    """
    Simple evaluation without OpenAI (just checks retrieval quality).
    """
    rag = BillShieldRAG()
    test_cases = create_test_dataset()

    print("="*70)
    print("BillShield RAG Evaluation (Simple)")
    print("="*70)

    total_score = 0

    for i, test in enumerate(test_cases, 1):
        print(f"\n{'='*70}")
        print(f"Test Case {i}/{len(test_cases)}")
        print(f"{'='*70}")
        print(f"Question: {test['question']}")
        print(f"Ground Truth: {test['ground_truth']}")

        # Retrieve context
        if "CGHS" in test['question'] or "ICU" in test['question']:
            results = rag.search_cghs_rates(test['question'], n_results=3)
            context = "\n".join([r['match_text'] for r in results])
        else:
            results = rag.search_irdai_regulations(
                test['question'],
                n_results=3,
                min_similarity=0.3
            )
            context = "\n".join([r['text'] for r in results])

        # Check if context contains expected keywords
        context_lower = context.lower()
        keywords_found = sum(1 for kw in test['context_keywords']
                            if kw.lower() in context_lower)

        score = keywords_found / len(test['context_keywords'])
        total_score += score

        print(f"\n📊 Keyword Match Score: {score:.2%}")
        print(f"   Keywords found: {keywords_found}/{len(test['context_keywords'])}")
        print(f"   Retrieved {len(results)} chunks")

        if score < 0.5:
            print(f"   ⚠️  LOW SCORE - Missing keywords: {[kw for kw in test['context_keywords'] if kw.lower() not in context_lower]}")

    avg_score = total_score / len(test_cases)

    print(f"\n{'='*70}")
    print(f"Overall RAG Quality Score: {avg_score:.2%}")
    print(f"{'='*70}")

    if avg_score >= 0.8:
        print("✅ EXCELLENT - RAG is retrieving highly relevant context")
    elif avg_score >= 0.6:
        print("✅ GOOD - RAG is working well, minor improvements possible")
    elif avg_score >= 0.4:
        print("⚠️  NEEDS IMPROVEMENT - Consider better chunking or more data")
    else:
        print("🔴 POOR - RAG needs significant improvement")

    return avg_score


def run_ragas_evaluation():
    """
    Full RAGAS evaluation using OpenAI (requires API key).
    """
    if not OPENAI_API_KEY:
        print("⚠️  OPENAI_API_KEY not set. Running simple evaluation instead.")
        return run_simple_evaluation()

    rag = BillShieldRAG()
    test_cases = create_test_dataset()

    # Prepare dataset for RAGAS
    data = {
        "question": [],
        "answer": [],
        "contexts": [],
        "ground_truth": []
    }

    print("Preparing evaluation dataset...")

    for test in test_cases:
        # Get retrieval results
        if "CGHS" in test['question'] or "ICU" in test['question']:
            results = rag.search_cghs_rates(test['question'], n_results=3)
            contexts = [r['match_text'] for r in results]
            rate_parts = [f"{r['procedure']}: ₹{r['rate']}" for r in results[:2]]
            answer = f"CGHS rates: {', '.join(rate_parts)}"
        else:
            results = rag.search_irdai_regulations(
                test['question'],
                n_results=3,
                min_similarity=0.3
            )
            contexts = [r['text'] for r in results]
            answer = f"Per IRDAI regulations: {contexts[0][:200]}..."

        data["question"].append(test['question'])
        data["answer"].append(answer)
        data["contexts"].append(contexts)
        data["ground_truth"].append(test['ground_truth'])

    dataset = Dataset.from_dict(data)

    # Run RAGAS evaluation
    print("\nRunning RAGAS evaluation (this may take 1-2 minutes)...")

    result = evaluate(
        dataset,
        metrics=[
            context_precision,
            context_recall,
            faithfulness,
            answer_relevancy
        ],
        llm=ChatOpenAI(model="gpt-3.5-turbo"),
        embeddings=OpenAIEmbeddings()
    )

    print("\n" + "="*70)
    print("RAGAS Evaluation Results")
    print("="*70)

    for metric, score in result.items():
        print(f"{metric}: {score:.3f}")

    return result


if __name__ == "__main__":
    # Check if OpenAI key is available
    if OPENAI_API_KEY:
        print("🔑 OpenAI API key found - running full RAGAS evaluation")
        run_ragas_evaluation()
    else:
        print("💡 No OpenAI API key - running simple keyword-based evaluation")
        print("   (Set OPENAI_API_KEY in .env for full RAGAS metrics)\n")
        run_simple_evaluation()