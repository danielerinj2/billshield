"""
Test RAG retrieval from ChromaDB.
"""
import chromadb
from chromadb.utils import embedding_functions

def test_irdai_retrieval():
    """Test retrieval from IRDAI regulations collection."""
    
    chroma_client = chromadb.PersistentClient(path="data/chromadb")
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )
    
    collection = chroma_client.get_collection(
        name="irdai_regulations",
        embedding_function=embedding_fn
    )
    
    print("="*70)
    print("Testing IRDAI Regulation Retrieval")
    print("="*70)
    
    test_queries = [
        "What is the 15-day claim settlement rule?",
        "How long does the insurer have to approve cashless authorization?",
        "What interest rate applies if claim settlement is delayed?",
        "What are the grievance redressal timelines?"
    ]
    
    for query in test_queries:
        print(f"\n🔍 Query: {query}")
        print("-" * 70)
        
        results = collection.query(
            query_texts=[query],
            n_results=2
        )
        
        for i, (doc, metadata, distance) in enumerate(zip(
            results['documents'][0],
            results['metadatas'][0],
            results['distances'][0]
        ), 1):
            print(f"\n  Result {i} (similarity: {1 - distance:.3f}):")
            print(f"  📄 Page {metadata['page']}, Section: {metadata['section']}")
            print(f"  📝 {doc[:300]}...")

def test_reference_retrieval():
    """Test retrieval from reference benchmarks collection."""
    
    chroma_client = chromadb.PersistentClient(path="data/chromadb")
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )
    
    collection = chroma_client.get_collection(
        name="reference_benchmarks",
        embedding_function=embedding_fn
    )
    
    print("\n\n" + "="*70)
    print("Testing Reference Benchmark Retrieval")
    print("="*70)
    
    test_queries = [
        "ICU charges per day",
        "CT scan cost",
        "Paracetamol tablet price",
        "consultation charges"
    ]
    
    for query in test_queries:
        print(f"\n🔍 Query: {query}")
        print("-" * 70)
        
        results = collection.query(
            query_texts=[query],
            n_results=3
        )
        
        for i, (doc, metadata, distance) in enumerate(zip(
            results['documents'][0],
            results['metadatas'][0],
            results['distances'][0]
        ), 1):
            print(f"\n  Result {i} (similarity: {1 - distance:.3f}):")
            print(f"  Type: {metadata.get('type', 'unknown')}")
            print(f"  📝 {doc[:200]}")

if __name__ == "__main__":
    test_irdai_retrieval()
    test_reference_retrieval()
    
    print("\n\n" + "="*70)
    print("✅ Retrieval tests complete!")
    print("="*70)