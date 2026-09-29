"""
Cloud Run Ingestion Worker: Listens to Eventarc GCS events or executes batch jobs
to ingest Carrier PDF manuals into Vector Search 2.0 with Gemini 2.5 Flash.
"""

import os
import sys
import json
import tempfile
from pathlib import Path
from typing import Dict, Any

from google.cloud import storage
from gemini_flash_ingestion import GeminiFlashIngestionEngine

MANUAL_METADATA_MAP = {
    "19XR": {"model": "19XR", "form": "19XR-CLT-9T"},
    "23XRV": {"model": "23XRV", "form": "23XRV-3T"},
    "30HX": {"model": "30HX", "form": "30HX-2T"},
    "30RC": {"model": "30RC", "form": "30RC-101T"},
    "30XV": {"model": "30XV", "form": "30XV-6T"},
}

def main():
    # Can receive GCS URI via environment variable (Cloud Run Job) or CLI arg
    gcs_pdf_uri = os.getenv("INPUT_GCS_PDF_URI", sys.argv[1] if len(sys.argv) > 1 else "")
    if not gcs_pdf_uri:
        print("[ERROR] No input PDF GCS URI provided. Set INPUT_GCS_PDF_URI or pass as argument.")
        sys.exit(1)

    print(f"Starting Gemini 2.5 Flash Cloud Run Ingestion Worker for: {gcs_pdf_uri}")
    
    # Infer model and form from filename
    filename = Path(gcs_pdf_uri).name.upper()
    matched_model = None
    for model_key, meta in MANUAL_METADATA_MAP.items():
        if model_key in filename:
            matched_model = meta
            break
            
    if not matched_model:
        matched_model = {"model": "GENERAL", "form": Path(gcs_pdf_uri).stem}

    # Download from GCS to local temp file
    storage_client = storage.Client()
    parts = gcs_pdf_uri.replace("gs://", "").split("/", 1)
    bucket_name, blob_name = parts[0], parts[1]
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        blob.download_to_filename(str(tmp_path))

    try:
        engine = GeminiFlashIngestionEngine()
        data_objects = engine.process_manual(
            pdf_path=tmp_path,
            model_series=matched_model["model"],
            form_number=matched_model["form"]
        )

        print(f"Successfully processed {len(data_objects)} objects from {filename} with Gemini 2.5 Flash. Ingesting into Vector Search 2.0...")
        total_ingested = engine.upload_to_vector_search(data_objects)
        print(f"[COMPLETE] Ingestion Job Finished: {total_ingested} objects loaded into Vector Search 2.0.")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

if __name__ == "__main__":
    main()
