#!/usr/bin/env python3
"""
Test script for Google Cloud Vector Search 2.0 (Agent Retrieval).
Reference:
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/vector-search-2/overview
- https://colab.sandbox.google.com/github/GoogleCloudPlatform/generative-ai/blob/main/embeddings/vector-search-2-intro.ipynb
"""

import argparse
import getpass
import json
import os
import sys
import time
from datetime import datetime
from google.cloud import vectorsearch_v1beta
from tqdm.auto import tqdm


def get_default_project():
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project:
        return project
    try:
        import google.auth
        _, project = google.auth.default()
        if project:
            return project
    except Exception:
        pass
    return "genai-demos-391416"


def load_thelook_sample(filepath: str, sample_size: int = 100):
    if not os.path.exists(filepath):
        print(f"📥 Downloading dataset from Google Cloud Storage to {filepath}...")
        import urllib.request
        url = "https://storage.googleapis.com/gcp-samples-ic0-vs20demo/thelook_dataset.jsonl"
        urllib.request.urlretrieve(url, filepath)

    products = []
    with open(filepath, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if idx >= sample_size:
                break
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            products.append(
                {
                    "id": str(item["id"]),
                    "data": {
                        "id": str(item["id"]),
                        "name": str(item["name"]),
                        "category": str(item["category"]),
                        "retail_price": float(item["retail_price"]),
                    },
                }
            )
    return products


def run_tests(project_id: str, location: str, sample_size: int, skip_ann: bool, keep_collection: bool):
    print("=" * 80)
    print("🚀 VECTOR SEARCH 2.0 (AGENT RETRIEVAL) END-TO-END TEST SUITE")
    print("=" * 80)
    print(f"Project ID:  {project_id}")
    print(f"Location:    {location}")
    print(f"Sample Size: {sample_size} products")
    print("=" * 80)

    # 1. Initialize Clients
    print("\n[Step 1] Initializing Vector Search 2.0 Clients...")
    vector_search_client = vectorsearch_v1beta.VectorSearchServiceClient()
    data_object_client = vectorsearch_v1beta.DataObjectServiceClient()
    search_client = vectorsearch_v1beta.DataObjectSearchServiceClient()
    print("✅ Successfully initialized clients:")
    print("   - VectorSearchServiceClient (Collections & Indexes)")
    print("   - DataObjectServiceClient (Data Ingestion & CRUD)")
    print("   - DataObjectSearchServiceClient (kNN, ANN, Text & Hybrid Search)")

    # 2. Create Collection
    user_str = getpass.getuser()
    timestamp_str = datetime.now().strftime("%m%d%y-%H%M%S")
    collection_id = f"test-vs20-{user_str}-{timestamp_str}"
    parent_location = f"projects/{project_id}/locations/{location}"
    collection_name = f"{parent_location}/collections/{collection_id}"

    print(f"\n[Step 2] Creating Collection: {collection_id}...")
    create_collection_req = vectorsearch_v1beta.CreateCollectionRequest(
        parent=parent_location,
        collection_id=collection_id,
        collection={
            "data_schema": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "category": {"type": "string"},
                    "retail_price": {"type": "number"},
                },
            },
            "vector_schema": {
                "name_dense_embedding": {
                    "dense_vector": {
                        "dimensions": 768,
                        "vertex_embedding_config": {
                            "model_id": "gemini-embedding-001",
                            "text_template": "{name}",
                            "task_type": "RETRIEVAL_DOCUMENT",
                        },
                    },
                },
            },
        },
    )

    op = vector_search_client.create_collection(request=create_collection_req)
    print("   Waiting for collection creation LRO...")
    collection_res = op.result()
    print(f"✅ Collection created successfully: {collection_res.name}")

    try:
        # Verify collection metadata
        get_col_req = vectorsearch_v1beta.GetCollectionRequest(name=collection_name)
        col = vector_search_client.get_collection(get_col_req)
        print(f"   Collection state: {col.state if hasattr(col, 'state') else 'ACTIVE'}")

        # 3. Load Sample Data
        print(f"\n[Step 3] Loading {sample_size} sample records from thelook_dataset.jsonl...")
        products = load_thelook_sample("thelook_dataset.jsonl", sample_size=sample_size)
        print(f"   Loaded {len(products)} products into memory.")

        # Test single Data Object creation to inspect auto-embeddings
        print("\n[Step 4] Testing Single Data Object Creation with Auto-Embeddings...")
        single_req = vectorsearch_v1beta.CreateDataObjectRequest(
            parent=collection_name,
            data_object_id=products[0]["id"],
            data_object={
                "data": products[0]["data"],
                "vectors": {},  # Empty vector map triggers automatic embedding generation
            },
        )
        single_obj = data_object_client.create_data_object(request=single_req)
        print(f"✅ Created Data Object {single_obj.name}")
        print(f"   Name:     {single_obj.data['name']}")
        print(f"   Category: {single_obj.data['category']}")
        print(f"   Price:    ${single_obj.data['retail_price']:.2f}")

        # Fetch it back to inspect auto-generated embedding vector
        fetched = data_object_client.get_data_object(
            vectorsearch_v1beta.GetDataObjectRequest(name=single_obj.name)
        )
        if "name_dense_embedding" in fetched.vectors:
            emb = fetched.vectors["name_dense_embedding"]
            dim = len(emb.dense_vector.values) if hasattr(emb, "dense_vector") else "unknown"
            print(f"✅ Verified Auto-Embedding: name_dense_embedding populated with {dim} dimensions!")
        else:
            print("ℹ️ Auto-embedding generating asynchronously in the background.")

        # 4. Batch Ingestion
        print(f"\n[Step 5] Ingesting remaining {len(products) - 1} products via BatchCreateDataObjects...")
        batch_size = 250
        remaining_products = products[1:]
        for batch_start in tqdm(range(0, len(remaining_products), batch_size), desc="Batch Ingesting"):
            batch_slice = remaining_products[batch_start : batch_start + batch_size]
            batch_req = [
                {
                    "data_object_id": p["id"],
                    "data_object": {
                        "data": p["data"],
                        "vectors": {},
                    },
                }
                for p in batch_slice
            ]
            data_object_client.batch_create_data_objects(
                vectorsearch_v1beta.BatchCreateDataObjectsRequest(
                    parent=collection_name,
                    requests=batch_req,
                )
            )
        print("✅ Batch ingestion completed.")

        # 5. Aggregations & Query Filtering
        print("\n[Step 6] Testing Aggregation & Filtering Queries...")
        # Count aggregation
        count_res = search_client.aggregate_data_objects(
            vectorsearch_v1beta.AggregateDataObjectsRequest(
                parent=collection_name,
                aggregate="COUNT",
            )
        )
        print(f"✅ Total Data Objects in Collection: {count_res}")

        # Structured query filter
        filter_query = {"retail_price": {"$lt": 40.0}}
        query_req = vectorsearch_v1beta.QueryDataObjectsRequest(
            parent=collection_name,
            filter=filter_query,
            output_fields=vectorsearch_v1beta.OutputFields(
                data_fields=["name", "category", "retail_price"]
            ),
        )
        query_results = list(search_client.query_data_objects(query_req))
        print(f"✅ Attribute filter (retail_price < $40): returned {len(query_results)} matches.")
        for r in query_results[:3]:
            print(f"   - {r.data['name']} (${r.data['retail_price']:.2f}) [{r.data['category']}]")

        # 6. Instant kNN Semantic Search
        print("\n[Step 7] Testing Instant kNN Semantic Search (Zero-Index Time)...")
        search_query = "outfit for summer beach party"
        sem_req = vectorsearch_v1beta.SearchDataObjectsRequest(
            parent=collection_name,
            semantic_search=vectorsearch_v1beta.SemanticSearch(
                search_text=search_query,
                search_field="name_dense_embedding",
                task_type="QUESTION_ANSWERING",
                top_k=5,
                output_fields=vectorsearch_v1beta.OutputFields(
                    data_fields=["name", "category", "retail_price"]
                ),
            ),
        )
        sem_res = search_client.search_data_objects(sem_req)
        print(f"Semantic search results for: '{search_query}':")
        for idx, res in enumerate(sem_res, 1):
            d = res.data_object.data
            print(f"   {idx}. {d['name']} | {d['category']} | ${d['retail_price']:.2f}")

        # 7. Semantic Search with Metadata Filter
        print("\n[Step 8] Testing Semantic Search + Combined Filter ($lt 50)...")
        filtered_sem_req = vectorsearch_v1beta.SearchDataObjectsRequest(
            parent=collection_name,
            semantic_search=vectorsearch_v1beta.SemanticSearch(
                search_text="casual jacket or shirt",
                search_field="name_dense_embedding",
                task_type="QUESTION_ANSWERING",
                top_k=5,
                filter={"retail_price": {"$lt": 50.0}},
                output_fields=vectorsearch_v1beta.OutputFields(
                    data_fields=["name", "category", "retail_price"]
                ),
            ),
        )
        filtered_res = search_client.search_data_objects(filtered_sem_req)
        print("Filtered semantic search results:")
        for idx, res in enumerate(filtered_res, 1):
            d = res.data_object.data
            print(f"   {idx}. {d['name']} | ${d['retail_price']:.2f}")

        # 8. Full-Text Search
        print("\n[Step 9] Testing Full-Text Keyword Search...")
        kw_query = "Dress"
        text_req = vectorsearch_v1beta.SearchDataObjectsRequest(
            parent=collection_name,
            text_search=vectorsearch_v1beta.TextSearch(
                search_text=kw_query,
                data_field_names=["name"],
                top_k=5,
                output_fields=vectorsearch_v1beta.OutputFields(
                    data_fields=["name", "category", "retail_price"]
                ),
            ),
        )
        text_res = search_client.search_data_objects(text_req)
        print(f"Text keyword search results for: '{kw_query}':")
        for idx, res in enumerate(text_res, 1):
            d = res.data_object.data
            print(f"   {idx}. {d['name']} | ${d['retail_price']:.2f}")

        # 9. Hybrid Search (Semantic + Full-Text with Reciprocal Rank Fusion)
        print("\n[Step 10] Testing Hybrid Search (Semantic + Full-Text with RRF Ranking)...")
        hybrid_query = "Silk casual dress"
        hybrid_req = vectorsearch_v1beta.BatchSearchDataObjectsRequest(
            parent=collection_name,
            searches=[
                vectorsearch_v1beta.Search(
                    semantic_search=vectorsearch_v1beta.SemanticSearch(
                        search_text=hybrid_query,
                        search_field="name_dense_embedding",
                        task_type="QUESTION_ANSWERING",
                        top_k=10,
                        output_fields=vectorsearch_v1beta.OutputFields(
                            data_fields=["name", "category", "retail_price"]
                        ),
                    )
                ),
                vectorsearch_v1beta.Search(
                    text_search=vectorsearch_v1beta.TextSearch(
                        search_text=hybrid_query,
                        data_field_names=["name"],
                        top_k=10,
                        output_fields=vectorsearch_v1beta.OutputFields(
                            data_fields=["name", "category", "retail_price"]
                        ),
                    )
                ),
            ],
            combine=vectorsearch_v1beta.BatchSearchDataObjectsRequest.CombineResultsOptions(
                ranker=vectorsearch_v1beta.Ranker(
                    rrf=vectorsearch_v1beta.ReciprocalRankFusion(weights=[1.0, 1.0])
                )
            ),
        )
        batch_res = search_client.batch_search_data_objects(hybrid_req)
        print("Hybrid search (RRF combined) results:")
        if batch_res.results and batch_res.results[0].results:
            for idx, res in enumerate(batch_res.results[0].results[:5], 1):
                d = res.data_object.data
                print(f"   {idx}. {d['name']} | ${d['retail_price']:.2f}")
        else:
            print("   (No hybrid matches found for query)")

        # 10. ANN Index (Optional)
        if not skip_ann:
            print("\n[Step 11] Creating ANN Index for Dense Embeddings (Note: Takes 15-30m)...")
            index_id = "name-dense-ann-idx"
            index_op = vector_search_client.create_index(
                vectorsearch_v1beta.CreateIndexRequest(
                    parent=collection_name,
                    index_id=index_id,
                    index={
                        "index_field": "name_dense_embedding",
                    },
                )
            )
            print("   Waiting for ANN index creation...")
            index_res = index_op.result()
            print(f"✅ ANN Index created: {index_res.name}")

            # Delete ANN Index
            print("   Deleting ANN Index...")
            del_idx_op = vector_search_client.delete_index(
                vectorsearch_v1beta.DeleteIndexRequest(name=f"{collection_name}/indexes/{index_id}")
            )
            del_idx_op.result()
            print("✅ ANN Index deleted.")
        else:
            print("\n[Step 11] Skipping ANN Index creation (--skip-ann is set).")

    finally:
        # Cleanup Collection
        if not keep_collection:
            print(f"\n[Cleanup] Deleting Collection {collection_id}...")
            try:
                vector_search_client.delete_collection(
                    vectorsearch_v1beta.DeleteCollectionRequest(name=collection_name, force=True)
                )
                print(f"✅ Successfully deleted Collection {collection_id}.")
            except Exception as e:
                print(f"⚠️ Warning during deletion: {e}")
        else:
            print(f"\n[Cleanup] Preserving Collection {collection_id} (--keep-collection is set).")

    print("\n" + "=" * 80)
    print("🎉 ALL VECTOR SEARCH 2.0 TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Test Vector Search 2.0 (Agent Retrieval)")
    parser.add_argument("--project", default=get_default_project(), help="GCP Project ID")
    parser.add_argument("--location", default="us-central1", help="GCP Location (default: us-central1)")
    parser.add_argument("--sample-size", type=int, default=100, help="Number of products to ingest (default: 100)")
    parser.add_argument("--skip-ann", action="store_true", default=True, help="Skip ANN index creation (takes 15-30m)")
    parser.add_argument("--with-ann", dest="skip_ann", action="store_false", help="Include ANN index creation")
    parser.add_argument("--keep-collection", action="store_true", help="Keep the collection after testing")
    args = parser.parse_args()

    run_tests(
        project_id=args.project,
        location=args.location,
        sample_size=args.sample_size,
        skip_ann=args.skip_ann,
        keep_collection=args.keep_collection,
    )


if __name__ == "__main__":
    main()
