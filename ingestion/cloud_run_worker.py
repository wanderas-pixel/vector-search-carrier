"""
Cloud Run Ingestion Worker: Listens to Eventarc GCS events or executes batch jobs
to ingest Carrier PDF manuals into Vector Search 2.0 with Document AI.
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, Any

from document_ai_ingestion import DocumentAIIngestionEngine

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

    print(f"Starting Cloud Run Ingestion Worker for: {gcs_pdf_uri}")
    
    # Infer model and form from filename
    filename = Path(gcs_pdf_uri).name.upper()
    matched_model = None
    for model_key, meta in MANUAL_METADATA_MAP.items():
        if model_key in filename:
            matched_model = meta
            break
            
    if not matched_model:
        matched_model = {"model": "GENERAL", "form": Path(gcs_pdf_uri).stem}

    engine = DocumentAIIngestionEngine()
    data_objects = engine.process_pdf_gcs(
        gcs_pdf_uri=gcs_pdf_uri,
        model_series=matched_model["model"],
        form_number=matched_model["form"]
    )

    print(f"Successfully processed {len(data_objects)} objects from {filename}. Ingesting into Vector Search 2.0...")
    total_ingested = engine.batch_upload_to_vector_search(data_objects)
    print(f"[COMPLETE] Ingestion Job Finished: {total_ingested} objects loaded.")

if __name__ == "__main__":
    main()
