"""
Load IRDAI chunks and reference data into ChromaDB for RAG retrieval.
"""

import json
import chromadb
from chromadb.utils import embedding_functions
from pathlib import Path


def load_irdai_to_chromadb(chunks_path: str, collection_name: str = "irdai_regulations"):
    """Load IRDAI chunks into ChromaDB."""

    chroma_client = chromadb.PersistentClient(path="data/chromadb")

    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )

    try:
        collection = chroma_client.get_collection(
            name=collection_name,
            embedding_function=embedding_fn
        )
        print(f"Found existing collection '{collection_name}' with {collection.count()} items")
        print("Deleting to reload...")
        chroma_client.delete_collection(name=collection_name)
    except:
        pass

    collection = chroma_client.create_collection(
        name=collection_name,
        embedding_function=embedding_fn,
        metadata={"description": "IRDAI Master Circular on Policyholders' Interests 2024"}
    )

    with open(chunks_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    chunks = data['chunks']
    print(f"\nLoading {len(chunks)} IRDAI chunks into ChromaDB...")

    ids = []
    documents = []
    metadatas = []

    for chunk in chunks:
        ids.append(chunk['chunk_id'])
        documents.append(chunk['text'])

        metadata = chunk["metadata"]

        clean_metadata = {}
        for key, value in metadata.items():
            if value is None:
                continue
            if isinstance(value, list):
                if len(value) == 0:
                    continue
                clean_metadata[key] = ", ".join(str(v) for v in value)
            else:
                clean_metadata[key] = value

        metadatas.append(clean_metadata)

    batch_size = 100
    for i in range(0, len(ids), batch_size):
        batch_end = min(i + batch_size, len(ids))
        collection.add(
            ids=ids[i:batch_end],
            documents=documents[i:batch_end],
            metadatas=metadatas[i:batch_end]
        )
        print(f"  Added batch {i//batch_size + 1}/{(len(ids) + batch_size - 1)//batch_size}")

    print(f"\n✅ Loaded {collection.count()} chunks into '{collection_name}'")

    return collection


def load_reference_data_to_chromadb(reference_dir: str = "data/reference"):
    """Load reference JSONs (CGHS, NPPA, etc) into ChromaDB."""

    chroma_client = chromadb.PersistentClient(path="data/chromadb")
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )

    collection_name = "reference_benchmarks"
    try:
        collection = chroma_client.get_collection(
            name=collection_name,
            embedding_function=embedding_fn
        )
        print(f"\nFound existing collection '{collection_name}', deleting...")
        chroma_client.delete_collection(name=collection_name)
    except:
        pass

    collection = chroma_client.create_collection(
        name=collection_name,
        embedding_function=embedding_fn,
        metadata={"description": "CGHS rates, NPPA drugs/devices, non-payable items"}
    )

    reference_files = {
        "cghs_rates.json": "cghs_rate",
        "nppa_drugs.json": "nppa_drug",
        "nppa_devices.json": "nppa_device",
        "non_payable_items.json": "non_payable",
        "drug_lookup.json": "drug_lookup"
    }

    total_loaded = 0

    for filename, doc_type in reference_files.items():
        filepath = Path(reference_dir) / filename
        if not filepath.exists():
            print(f"⚠️  Skipping {filename} (not found)")
            continue

        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Handle different structures
        if isinstance(data, dict):
            # Check for wrapper objects
            if 'entries' in data:
                items = data['entries']  # NPPA structure
            elif 'rates' in data:
                items = data['rates']
            elif 'drugs' in data:
                items = data['drugs']
            elif 'items' in data:
                items = data['items']
            else:
                # Single item or already the data
                items = [data] if not isinstance(data, list) else data
        elif isinstance(data, list):
            items = data
        else:
            print(f"⚠️  Unexpected format in {filename}")
            continue

        print(f"\nLoading {filename}: {len(items)} items")

        ids = []
        documents = []
        metadatas = []

        for i, item in enumerate(items):
            # Create searchable text
            if doc_type == "cghs_rate":
                # Pick best available rate
                rate = (item.get('rate_nabh') or
                        item.get('rate_non_nabh') or
                        item.get('rate_super_speciality') or 0)

                text = (f"{item.get('procedure', '')} "
                        f"Rate: ₹{rate} "
                        f"Speciality: {item.get('speciality', '')} "
                        f"City: {item.get('city_tier', '')}")

                metadata = {
                    "type": "cghs_rate",
                    "procedure": item.get('procedure', ''),
                    "rate": float(rate),
                    "rate_nabh": item.get('rate_nabh', 0),
                    "rate_non_nabh": item.get('rate_non_nabh', 0),
                    "speciality": item.get('speciality', ''),
                    "category": item.get('speciality', '')
                }

            elif doc_type == "nppa_drug":
                ceiling = item.get('ceiling_price_inr', 0)
                text = (f"{item.get('drug_name', '')} "
                        f"{item.get('dosage_form_strength', '')} "
                        f"MRP: ₹{ceiling}")

                metadata = {
                    "type": "nppa_drug",
                    "drug_name": item.get('drug_name', ''),
                    "dosage_form_strength": item.get('dosage_form_strength', ''),
                    "ceiling_price": float(ceiling)
                }

            elif doc_type == "nppa_device":
                ceiling = item.get('ceiling_price_inr', 0)
                text = (f"{item.get('device_name', '')} "
                        f"{item.get('specifications', '')} "
                        f"MRP: ₹{ceiling}")

                metadata = {
                    "type": "nppa_device",
                    "device_name": item.get('device_name', ''),
                    "ceiling_price": float(ceiling)
                }

            elif doc_type == "non_payable":
                text = f"Non-payable: {item.get('item', '')} Reason: {item.get('reason', '')}"
                metadata = {
                    "type": "non_payable",
                    "item": item.get('item', ''),
                    "category": item.get('category', ''),
                    "reason": item.get('reason', '')
                }

            elif doc_type == "drug_lookup":
                text = (f"{item.get('generic_name', '')} "
                        f"{item.get('brand_name', '')} "
                        f"MRP: ₹{item.get('mrp', 0)}")

                metadata = {
                    "type": "drug_lookup",
                    "generic_name": item.get('generic_name', ''),
                    "brand_name": item.get('brand_name', ''),
                    "mrp": item.get('mrp', 0)
                }

            else:
                text = json.dumps(item)
                metadata = {"type": doc_type}

            ids.append(f"{doc_type}_{i}")
            documents.append(text)
            metadatas.append(metadata)

        # Add in batches
        batch_size = 500
        for i in range(0, len(ids), batch_size):
            batch_end = min(i + batch_size, len(ids))
            collection.add(
                ids=ids[i:batch_end],
                documents=documents[i:batch_end],
                metadatas=metadatas[i:batch_end]
            )

        total_loaded += len(items)
        print(f"  ✅ Loaded {len(items)} {doc_type} entries")

    print(f"\n✅ Total reference items loaded: {total_loaded}")
    return collection


def load_policy_to_chromadb(
    chunks_path: str,
    collection_name: str = "user_policy"
):
    """
    Load user policy chunks into ChromaDB.
    Each user gets their own collection to prevent data mixing.
    """
    chroma_client = chromadb.PersistentClient(path="data/chromadb")
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )
    
    # Delete existing collection if exists
    try:
        collection = chroma_client.get_collection(
            name=collection_name,
            embedding_function=embedding_fn
        )
        print(f"Found existing collection '{collection_name}', deleting...")
        chroma_client.delete_collection(name=collection_name)
    except:
        pass
    
    # Create new collection
    collection = chroma_client.create_collection(
        name=collection_name,
        embedding_function=embedding_fn,
        metadata={"description": "User-uploaded insurance policy"}
    )
    
    # Load chunks
    with open(chunks_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    chunks = data['chunks']
    print(f"\nLoading {len(chunks)} policy chunks into ChromaDB...")
    
    # Prepare data
    ids = []
    documents = []
    metadatas = []
    
    for chunk in chunks:
        ids.append(chunk['chunk_id'])
        documents.append(chunk['text'])

        metadata = chunk["metadata"]

        clean_metadata = {}
        for key, value in metadata.items():
            if value is None:
                continue
            if isinstance(value, list):
                if len(value) == 0:
                    continue
                clean_metadata[key] = ", ".join(str(v) for v in value)
            else:
                clean_metadata[key] = value

        metadatas.append(clean_metadata)
    
    # Add to collection
    collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas
    )
    
    print(f"✅ Loaded {collection.count()} policy chunks into '{collection_name}'")
    return collection


if __name__ == "__main__":
    # Load IRDAI chunks
    irdai_collection = load_irdai_to_chromadb(
        chunks_path="data/reference/irdai_master_circular_chunks.json"
    )

    # Load reference data
    ref_collection = load_reference_data_to_chromadb()

    print("\n" + "="*60)
    print("✅ ChromaDB setup complete!")
    print("="*60)
    print(f"IRDAI regulations: {irdai_collection.count()} chunks")
    print(f"Reference benchmarks: {ref_collection.count()} items")
    print(f"Storage location: data/chromadb/")