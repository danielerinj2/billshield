"""
RAG retrieval functions for BillShield agent.
"""
import chromadb
from chromadb.utils import embedding_functions
from typing import List, Dict


class BillShieldRAG:
    """RAG retrieval system for BillShield."""
    
    def __init__(self, chromadb_path: str = "data/chromadb"):
        """Initialize RAG system with ChromaDB."""
        self.client = chromadb.PersistentClient(path=chromadb_path)
        self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        
        # Load collections
        self.irdai_collection = self.client.get_collection(
            name="irdai_regulations",
            embedding_function=self.embedding_function
        )
        
        self.reference_collection = self.client.get_collection(
            name="reference_benchmarks",
            embedding_function=self.embedding_function
        )
        
        # Load policy collection (optional, might not exist)
        try:
            self.policy_collection = self.client.get_collection(
                name="policy_exclusions",
                embedding_function=self.embedding_function
            )
        except:
            self.policy_collection = None
            print("⚠️  Policy exclusions collection not found")
    
    def search_irdai_regulations(
        self, 
        query: str, 
        n_results: int = 3,
        min_similarity: float = 0.5
    ) -> List[Dict]:
        """
        Search IRDAI regulations for relevant clauses.
        
        Args:
            query: Natural language query (e.g., "claim settlement timeline")
            n_results: Number of results to return
            min_similarity: Minimum similarity threshold (0-1)
        
        Returns:
            List of dicts with keys: text, page, section, reference, similarity
        """
        results = self.irdai_collection.query(
            query_texts=[query],
            n_results=n_results
        )
        
        formatted_results = []
        for doc, metadata, distance in zip(
            results['documents'][0],
            results['metadatas'][0],
            results['distances'][0]
        ):
            similarity = 1 - distance
            
            if similarity >= min_similarity:
                formatted_results.append({
                    "text": doc,
                    "page": metadata['page'],
                    "section": metadata['section'],
                    "reference": metadata['reference'],
                    "document": metadata['document'],
                    "date": metadata['date'],
                    "similarity": round(similarity, 3)
                })
        
        return formatted_results

    def search_policy_exclusions(self, query: str, n_results: int = 3) -> List[Dict]:
        """
        Search sample policy exclusion clauses.
        
        Args:
            query: Search query (e.g., "pre-existing condition exclusion")
            n_results: Number of results to return
        
        Returns:
            List of policy exclusion chunks with metadata
        """
        try:
            results = self.policy_collection.query(
                query_texts=[query],
                n_results=n_results
            )
            
            chunks = []
            if results['documents'][0]:
                for i, doc in enumerate(results['documents'][0]):
                    metadata = results['metadatas'][0][i]
                    chunks.append({
                        'text': doc,
                        'chunk_id': metadata.get('chunk_id', ''),
                        'clause_number': metadata.get('clause_number', ''),
                        'keywords': metadata.get('keywords', '').split(','),
                        'similarity': 1 - results['distances'][0][i]
                    })
            
            return chunks
        except Exception as e:
            print(f"Error searching policy exclusions: {e}")
            return []
    
    def search_cghs_rates(
        self, 
        procedure: str, 
        n_results: int = 5
    ) -> List[Dict]:
        """
        Search CGHS rate card for procedure pricing.
        
        Args:
            procedure: Procedure name (e.g., "ICU per day", "CT scan")
            n_results: Number of results to return
        
        Returns:
            List of dicts with procedure details and rates
        """
        results = self.reference_collection.query(
            query_texts=[procedure],
            n_results=n_results,
            where={"type": "cghs_rate"}
        )
        
        formatted_results = []
        for doc, metadata, distance in zip(
            results['documents'][0],
            results['metadatas'][0],
            results['distances'][0]
        ):
            similarity = 1 - distance
            
            formatted_results.append({
                "procedure": metadata.get('procedure', ''),
                "rate": metadata.get('rate', 0),
                "category": metadata.get('category', ''),
                "similarity": round(similarity, 3),
                "match_text": doc
            })
        
        return formatted_results
    
    def search_non_payable_items(
        self, 
        item: str, 
        n_results: int = 5
    ) -> List[Dict]:
        """
        Search for non-payable items per IRDAI guidelines.
        
        Args:
            item: Item description
            n_results: Number of results to return
        
        Returns:
            List of dicts with non-payable item details
        """
        results = self.reference_collection.query(
            query_texts=[item],
            n_results=n_results,
            where={"type": "non_payable"}
        )
        
        formatted_results = []
        for doc, metadata, distance in zip(
            results['documents'][0],
            results['metadatas'][0],
            results['distances'][0]
        ):
            similarity = 1 - distance
            
            formatted_results.append({
                "item": metadata.get('item', ''),
                "category": metadata.get('category', ''),
                "similarity": round(similarity, 3),
                "match_text": doc
            })
        
        return formatted_results

    def search_policy(
        self,
        query: str,
        n_results: int = 3,
        collection_name: str = "user_policy"
    ) -> List[Dict]:
        """
        Search user's insurance policy for relevant clauses.
        
        Args:
            query: Natural language query (e.g., "room rent limit", "exclusions")
            n_results: Number of results to return
            collection_name: Policy collection name (default: "user_policy")
        
        Returns:
            List of dicts with policy text, page, section, metadata
        """
        try:
            policy_collection = self.client.get_collection(
                name=collection_name,
                embedding_function=self.embedding_function
            )
        except:
            return []  # No policy loaded
        
        results = policy_collection.query(
            query_texts=[query],
            n_results=n_results
        )
        
        formatted_results = []
        for doc, metadata, distance in zip(
            results['documents'][0],
            results['metadatas'][0],
            results['distances'][0]
        ):
            similarity = 1 - distance
            
            formatted_results.append({
                "text": doc,
                "page": metadata['page'],
                "section": metadata['section'],
                "policy_name": metadata.get('policy_name', 'User Policy'),
                "sections_mentioned": metadata.get('sections_mentioned', []),
                "monetary_limits": metadata.get('monetary_limits', []),
                "similarity": round(similarity, 3)
            })
        
        return formatted_results


# Convenience functions for agent tools
def lookup_irdai_regulation(query: str) -> str:
    """
    Agent tool: Look up IRDAI regulation by natural language query.
    Returns formatted citation.
    """
    rag = BillShieldRAG()
    results = rag.search_irdai_regulations(query, n_results=2)
    
    if not results:
        return f"No IRDAI regulation found for: {query}"
    
    # Format as citation
    citations = []
    for i, result in enumerate(results, 1):
        citations.append(
            f"[{i}] {result['document']} (Ref: {result['reference']}, "
            f"Page {result['page']}, Section: {result['section']})\n"
            f"Excerpt: {result['text'][:300]}..."
        )
    
    return "\n\n".join(citations)


def lookup_cghs_rate(procedure: str) -> str:
    """
    Agent tool: Look up CGHS rate for a procedure.
    Returns formatted rate info.
    """
    rag = BillShieldRAG()
    results = rag.search_cghs_rates(procedure, n_results=3)
    
    if not results:
        return f"No CGHS rate found for: {procedure}"
    
    # Format results
    rate_info = [f"CGHS rates for '{procedure}':"]
    for result in results:
        if result['rate'] > 0:  # Filter out ₹0 entries
            rate_info.append(
                f"  - {result['procedure']}: ₹{result['rate']:,.2f} "
                f"(Category: {result['category']})"
            )
    
    if len(rate_info) == 1:
        return f"No valid CGHS rates found for: {procedure}"
    
    return "\n".join(rate_info)


def lookup_policy_clause(query: str) -> str:
    """
    Agent tool: Look up user's policy for relevant clauses.
    Returns formatted policy excerpt.
    """
    rag = BillShieldRAG()
    results = rag.search_policy(query, n_results=2)
    
    if not results:
        return "No policy document found. User has not uploaded their insurance policy."
    
    # Format results
    citations = []
    for i, result in enumerate(results, 1):
        citations.append(
            f"[{i}] {result['policy_name']} (Page {result['page']}, Section: {result['section']})\n"
            f"Excerpt: {result['text'][:300]}..."
        )
    
    return "\n\n".join(citations)


if __name__ == "__main__":
    # Quick test
    print("Testing agent-facing functions:\n")
    
    print("1. IRDAI Regulation Lookup:")
    print(lookup_irdai_regulation("15 day claim settlement rule"))
    
    print("\n\n2. CGHS Rate Lookup:")
    print(lookup_cghs_rate("ICU charges"))
    
    print("\n\n3. Policy Exclusion Lookup:")
    rag = BillShieldRAG()
    policy_results = rag.search_policy_exclusions("cosmetic dental pregnancy exclusions", n_results=2)
    for result in policy_results:
        print(f"Clause {result['clause_number']} | Similarity: {result['similarity']:.3f}")
        print(result['text'][:300])
        print()