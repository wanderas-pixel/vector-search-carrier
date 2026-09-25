"""
Vector Search 2.0 (Agent Retrieval) Provisioning & Ingestion Engine.
Provisions the 'carrier-chiller-docs' collection with dual vectors (text_embedding + visual_embedding),
configures server-side auto-embeddings via 'gemini-embedding-001', and batch ingests data objects.
"""

import os
import sys
import json
import time
from pathlib import Path
from typing import List, Dict, Any

from google.cloud import vectorsearch_v1beta
from google.api_core.exceptions import AlreadyExists, NotFound
from tqdm import tqdm

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "genai-demos-391416")
LOCATION = os.getenv("GOOGLE_CLOUD_REGION", "us-central1")
COLLECTION_ID = "carrier-chiller-docs"
JSONL_INPUT = Path("carrier_documents.jsonl")

PARENT = f"projects/{PROJECT_ID}/locations/{LOCATION}"
COLLECTION_NAME = f"{PARENT}/collections/{COLLECTION_ID}"

DATA_SCHEMA = {
    "type": "object",
    "properties": {
        "chunk_id": {"type": "string"},
        "model_series": {"type": "string"},
        "form_number": {"type": "string"},
        "section": {"type": "string"},
        "page_number": {"type": "integer"},
        "content_type": {"type": "string"},
        "content": {"type": "string"},
        "has_image": {"type": "boolean"},
        "image_url": {"type": "string"},
        "diagram_caption": {"type": "string"},
        "diagram_ocr_details": {"type": "string"}
    },
    "required": ["chunk_id", "model_series", "form_number", "page_number", "content"]
}

VECTOR_SCHEMA = {
    "text_embedding": {
        "dense_vector": {
            "dimensions": 768,
            "vertex_embedding_config": {
                "model_id": "gemini-embedding-001",
                "text_template": "Equipment: {model_series} | Manual: {form_number} | Section: {section} | Page: {page_number}\n\nDiagram: {diagram_caption}\n\nContent:\n{content}",
                "task_type": "RETRIEVAL_DOCUMENT"
            }
        }
    },
    "visual_embedding": {
        "dense_vector": {
            "dimensions": 1408
        }
    }
}


def create_or_get_collection(client: vectorsearch_v1beta.VectorSearchServiceClient) -> Any:
    """Creates the Vector Search 2.0 collection if it does not already exist."""
    try:
        col = client.get_collection(name=COLLECTION_NAME)
        print(f"[FOUND] Vector Search 2.0 Collection '{COLLECTION_ID}' already exists.")
        return col
    except NotFound:
        print(f"[CREATING] Collection '{COLLECTION_ID}' in {PARENT}...")
        collection = vectorsearch_v1beta.Collection(
            display_name="Carrier Chiller Engineering Manuals",
            description="Carrier Commercial Chillers (19XR, 23XRV, 30HX, 30RC, 30XV) with Text and Multimodal Vectors",
            data_schema=DATA_SCHEMA,
            vector_schema=VECTOR_SCHEMA,
        )
        op = client.create_collection(
            parent=PARENT,
            collection_id=COLLECTION_ID,
            collection=collection
        )
        print("Waiting for collection provisioning...")
        col = op.result()
        print(f"[SUCCESS] Collection '{COLLECTION_ID}' created successfully!")
        return col


def batch_ingest_objects(
    client: vectorsearch_v1beta.DataObjectServiceClient,
    jsonl_path: Path,
    batch_size: int = 100
):
    """Batch ingests data objects from JSONL into Vector Search 2.0 with instant kNN availability."""
    if not jsonl_path.exists():
        print(f"[ERROR] Ingestion file not found: {jsonl_path}")
        sys.exit(1)

    print(f"\nReading objects from {jsonl_path}...")
    raw_items = []
    with open(jsonl_path, "r") as f:
        for line in f:
            if line.strip():
                raw_items.append(json.loads(line.strip()))

    total_objects = len(raw_items)
    print(f"Total objects to ingest: {total_objects}")

    # Chunk into batches of batch_size
    batches = [raw_items[i:i + batch_size] for i in range(0, total_objects, batch_size)]
    
    print(f"Ingesting {len(batches)} batches into Vector Search 2.0...")
    for idx, batch in enumerate(tqdm(batches, desc="Batch Ingestion")):
        batch_req_items = []
        for item in batch:
            chunk_id = item["data"]["chunk_id"]
            do_data = item["data"]
            vectors = {}
            if "vectors" in item and "visual_embedding" in item["vectors"]:
                vectors["visual_embedding"] = {
                    "dense": {
                        "values": item["vectors"]["visual_embedding"]["values"]
                    }
                }
            batch_req_items.append({
                "data_object_id": chunk_id,
                "data_object": {
                    "data": do_data,
                    "vectors": vectors
                }
            })

        req = vectorsearch_v1beta.BatchCreateDataObjectsRequest(
            parent=COLLECTION_NAME,
            requests=batch_req_items
        )
        try:
            client.batch_create_data_objects(request=req)
        except AlreadyExists:
            pass
        except Exception as e:
            print(f"\n[WARN] Batch {idx+1} notice: {e}. Retrying in 2 seconds...")
            time.sleep(2)
            try:
                client.batch_create_data_objects(request=req)
            except Exception as e2:
                print(f"[ERROR] Batch {idx+1} error: {e2}")

    print(f"\n[COMPLETE] Successfully ingested {total_objects} data objects into Vector Search 2.0!")


def verify_instant_search(search_client: vectorsearch_v1beta.DataObjectSearchServiceClient):
    """Executes a test hybrid search to verify instant kNN functionality."""
    print("\n--------------------------------------------------")
    print("Executing Verification Search on Vector Search 2.0...")
    test_query = "What is alarm code T051 and probable causes?"
    start_t = time.time()
    
    hybrid_req = vectorsearch_v1beta.BatchSearchDataObjectsRequest(
        parent=COLLECTION_NAME,
        searches=[
            vectorsearch_v1beta.Search(
                semantic_search=vectorsearch_v1beta.SemanticSearch(
                    search_text=test_query,
                    search_field="text_embedding",
                    task_type="QUESTION_ANSWERING",
                    filter={"model_series": {"$eq": "30XV"}},
                    top_k=5,
                    output_fields=vectorsearch_v1beta.OutputFields(
                        data_fields=["chunk_id", "model_series", "form_number", "page_number", "section", "content", "has_image", "image_url"]
                    ),
                )
            ),
            vectorsearch_v1beta.Search(
                text_search=vectorsearch_v1beta.TextSearch(
                    search_text="T051 alarm",
                    data_field_names=["content"],
                    top_k=5,
                    output_fields=vectorsearch_v1beta.OutputFields(
                        data_fields=["chunk_id", "model_series", "form_number", "page_number", "section", "content", "has_image", "image_url"]
                    ),
                )
            ),
        ],
        combine=vectorsearch_v1beta.BatchSearchDataObjectsRequest.CombineResultsOptions(
            ranker=vectorsearch_v1beta.Ranker(
                rrf=vectorsearch_v1beta.ReciprocalRankFusion(weights=[1.0, 1.0])
            )
        )
    )
    
    response = search_client.batch_search_data_objects(request=hybrid_req)
    latency_ms = (time.time() - start_t) * 1000
    
    print(f"[VERIFIED] Hybrid Search completed in {latency_ms:.1f} ms!")
    if response.results and response.results[0].results:
        for idx, res in enumerate(response.results[0].results[:5], 1):
            d = dict(res.data_object.data)
            print(f"Match #{idx} | Form: {d.get('form_number')} | Page: {d.get('page_number')} | Section: {d.get('section')}")
            print(f"Snippet: {str(d.get('content'))[:180]}...\n")
    else:
        print("[NOTICE] Query returned zero results.")


def main():
    print("==================================================")
    print("Vector Search 2.0 (Agent Retrieval) Provisioning")
    print(f"Project: {PROJECT_ID} | Region: {LOCATION}")
    print(f"Target Collection: {COLLECTION_NAME}")
    print("==================================================")
    
    vector_search_client = vectorsearch_v1beta.VectorSearchServiceClient()
    data_object_client = vectorsearch_v1beta.DataObjectServiceClient()
    search_client = vectorsearch_v1beta.DataObjectSearchServiceClient()
    
    create_or_get_collection(vector_search_client)
    batch_ingest_objects(data_object_client, JSONL_INPUT)
    verify_instant_search(search_client)


if __name__ == "__main__":
    main()
