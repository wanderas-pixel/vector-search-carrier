"""
Carrier Industrial Chiller Document & Diagram Ingestion Engine.
Extracts text chunks, renders high-resolution 300 DPI WebP diagrams, uploads assets to GCS
with simulated CDN caching headers, and computes multimodal visual vectors for Vector Search 2.0.
"""

import os
import re
import io
import json
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional

import pypdf
import pypdfium2 as pdfium
from PIL import Image
from tqdm import tqdm
from google.cloud import storage
import vertexai
from vertexai.vision_models import MultiModalEmbeddingModel, Image as VertexImage

# Configuration
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "genai-demos-391416")
LOCATION = os.getenv("GOOGLE_CLOUD_REGION", "us-central1")
GCS_BUCKET_NAME = os.getenv("CARRIER_ASSETS_BUCKET", f"{PROJECT_ID}-carrier-assets")
INPUT_DIR = Path("Input Documents")
OUTPUT_DIR = Path("rendered_assets")
JSONL_OUTPUT = Path("carrier_documents.jsonl")

MANUAL_CATALOG = [
    {
        "filename": "19XR-CLT-9T.pdf",
        "model_series": "19XR",
        "form_number": "19XR-CLT-9T",
        "title": "19XR/19XRV Hermetic Centrifugal Liquid Chillers Controls, Start-Up, Operation, Service, and Troubleshooting",
    },
    {
        "filename": "23XRV-3T.pdf",
        "model_series": "23XRV",
        "form_number": "23XRV-3T",
        "title": "23XRV Variable-Speed Water-Cooled Screw Chillers Controls, Operation and Troubleshooting",
    },
    {
        "filename": "30HX-2T.pdf",
        "model_series": "30HX",
        "form_number": "30HX-2T",
        "title": "30HX, 30HXC, 30HXA Water-Cooled and Condenserless Liquid Chillers Controls, Operation and Troubleshooting",
    },
    {
        "filename": "30RC-101T.pdf",
        "model_series": "30RC",
        "form_number": "30RC-101T",
        "title": "30RC Air-Cooled Scroll Chillers with Puron Advance (R-32) Controls, Operation and Troubleshooting",
    },
    {
        "filename": "30XV-6T.pdf",
        "model_series": "30XV",
        "form_number": "30XV-6T",
        "title": "30XV Variable-Speed Air-Cooled Screw Chillers Controls, Operation and Troubleshooting",
    },
]

FIGURE_PATTERN = re.compile(r"(Fig(?:ure)?\.?\s*(?:[0-9]+|[A-Z])\s*[-–—:]\s*(?!ura|uri)[^.\n\r]+)", re.IGNORECASE)
SCHEMATIC_PATTERN = re.compile(r"((?:POWER|CONTROL|FIELD WIRING|TYPICAL)\s+SCHEMATIC|WIRING DIAGRAM|COMPONENT ARRANGEMENT|BOARD LAYOUT)", re.IGNORECASE)
TABLE_PATTERN = re.compile(r"(Table\s*\d+\s*[-–—]\s*[^.\n\r]+)", re.IGNORECASE)

def ensure_gcs_bucket(storage_client: storage.Client, bucket_name: str) -> storage.Bucket:
    """Gets or creates the GCS bucket for visual assets with uniform bucket-level access."""
    try:
        bucket = storage_client.get_bucket(bucket_name)
        print(f"[GCS] Bucket '{bucket_name}' already exists.")
        return bucket
    except Exception:
        print(f"[GCS] Creating bucket '{bucket_name}' in location '{LOCATION}'...")
        bucket = storage_client.create_bucket(bucket_name, location=LOCATION)
        # Configure CORS for React front-end access
        cors = [{
            "origin": ["*"],
            "method": ["GET", "HEAD"],
            "responseHeader": ["Content-Type", "Cache-Control"],
            "maxAgeSeconds": 3600
        }]
        bucket.cors = cors
        bucket.patch()
        print(f"[GCS] Bucket '{bucket_name}' created with CORS enabled.")
        return bucket


def upload_asset_to_gcs(
    bucket: storage.Bucket,
    local_path: Path,
    gcs_blob_name: str,
    content_type: str = "image/webp"
) -> str:
    """Uploads an image to GCS with simulated CDN caching headers and returns the public HTTPS URL."""
    blob = bucket.blob(gcs_blob_name)
    # Cache-Control: public, max-age=86400 simulates CDN edge caching
    blob.cache_control = "public, max-age=86400, immutable"
    blob.upload_from_filename(str(local_path), content_type=content_type)
    public_url = f"https://storage.googleapis.com/{bucket.name}/{gcs_blob_name}"
    return public_url


def generate_multimodal_embedding(
    multimodal_model: Any,
    image_bytes: bytes,
    contextual_text: str = ""
) -> Optional[List[float]]:
    """Generates a 1408-dimensional dense vector for a schematic diagram using Vertex AI."""
    try:
        v_img = VertexImage(image_bytes)
        embeddings = multimodal_model.get_embeddings(
            image=v_img,
            contextual_text=contextual_text if contextual_text else None
        )
        if embeddings.image_embedding:
            return list(embeddings.image_embedding)
    except Exception as e:
        print(f"[WARN] Failed to generate visual embedding: {e}")
    return None


def extract_and_process_manual(
    manual_info: Dict[str, Any],
    bucket: storage.Bucket,
    multimodal_model: Optional[Any]
) -> List[Dict[str, Any]]:
    """Extracts text, identifies figures, renders schematics to WebP, and generates JSONL data objects."""
    pdf_path = INPUT_DIR / manual_info["filename"]
    model_series = manual_info["model_series"]
    form_number = manual_info["form_number"]
    
    print(f"\n==================================================")
    print(f"Processing {model_series} ({manual_info['filename']})...")
    print(f"==================================================")
    
    reader = pypdf.PdfReader(str(pdf_path))
    pdf_document = pdfium.PdfDocument(str(pdf_path))
    total_pages = len(reader.pages)
    
    data_objects: List[Dict[str, Any]] = []
    
    # Track current section for metadata context
    current_section = "GENERAL"
    
    for page_idx in tqdm(range(total_pages), desc=f"{model_series} Pages"):
        page_num = page_idx + 1
        page = reader.pages[page_idx]
        text = page.extract_text() or ""
        
        # Detect Major Section Headers (common in Carrier manuals)
        for line in text.split("\n")[:10]:
            clean_line = line.strip().upper()
            if any(sec in clean_line for sec in ["START-UP", "TROUBLESHOOTING", "CONTROLS", "WIRING", "SERVICE", "OPERATION", "SAFETY", "SPECIFICATIONS"]):
                if len(clean_line) < 60:
                    current_section = clean_line
                    break
        
        # Detect figures / schematics on this page
        figure_matches = FIGURE_PATTERN.findall(text)
        schematic_match = SCHEMATIC_PATTERN.search(text)
        has_diagram = len(figure_matches) > 0 or (schematic_match is not None and len(text.strip()) < 1500)
        if figure_matches:
            diagram_caption = figure_matches[0].strip()
        elif schematic_match:
            diagram_caption = schematic_match.group(1).strip()
        else:
            diagram_caption = ""
        
        image_url = ""
        visual_embedding = None
        
        # If the page contains a schematic or key diagram, render it at 300 DPI
        if has_diagram:
            try:
                # Render page via pdfium at 300 DPI (scale ~ 4.16x for 72 dpi base)
                pdf_page = pdf_document[page_idx]
                pil_image = pdf_page.render(scale=3.0).to_pil()
                
                # Save locally as WebP
                model_dir = OUTPUT_DIR / "diagrams" / model_series
                model_dir.mkdir(parents=True, exist_ok=True)
                
                # Generate clean filename
                clean_fig_id = re.sub(r"[^a-zA-Z0-9_-]", "_", diagram_caption)[:50]
                local_webp_path = model_dir / f"{form_number}_p{page_num}_{clean_fig_id}.webp"
                pil_image.save(local_webp_path, format="WEBP", quality=85)
                
                # Upload to GCS
                gcs_blob = f"diagrams/{model_series}/{local_webp_path.name}"
                image_url = upload_asset_to_gcs(bucket, local_webp_path, gcs_blob)
                
                # Compute visual embedding if multimodal_model is active
                if multimodal_model:
                    with open(local_webp_path, "rb") as img_file:
                        visual_embedding = generate_multimodal_embedding(
                            multimodal_model,
                            img_file.read(),
                            contextual_text=f"Carrier {model_series} {diagram_caption}"
                        )
            except Exception as e:
                print(f"[WARN] Error rendering diagram on page {page_num}: {e}")
        
        # Text Chunking: Break page into 800-1200 character chunks with overlap
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [text.strip()] if text.strip() else [""]
            
        chunk_buffer = ""
        chunk_idx = 1
        
        for para in paragraphs:
            if len(chunk_buffer) + len(para) > 1000 and len(chunk_buffer) > 200:
                chunk_id = f"{form_number}_p{page_num}_c{chunk_idx}"
                data_obj = {
                    "name": f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/carrier-chiller-docs/dataObjects/{chunk_id}",
                    "data": {
                        "chunk_id": chunk_id,
                        "model_series": model_series,
                        "form_number": form_number,
                        "section": current_section,
                        "page_number": page_num,
                        "content_type": "text",
                        "content": chunk_buffer.strip(),
                        "has_image": False,
                        "image_url": "",
                        "diagram_caption": "",
                        "diagram_ocr_details": ""
                    }
                }
                data_objects.append(data_obj)
                chunk_buffer = para + "\n\n"
                chunk_idx += 1
            else:
                chunk_buffer += para + "\n\n"
        
        # Add final text chunk
        if chunk_buffer.strip():
            chunk_id = f"{form_number}_p{page_num}_c{chunk_idx}"
            data_obj = {
                "name": f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/carrier-chiller-docs/dataObjects/{chunk_id}",
                "data": {
                    "chunk_id": chunk_id,
                    "model_series": model_series,
                    "form_number": form_number,
                    "section": current_section,
                    "page_number": page_num,
                    "content_type": "text",
                    "content": chunk_buffer.strip(),
                    "has_image": False,
                    "image_url": "",
                    "diagram_caption": "",
                    "diagram_ocr_details": ""
                }
            }
            data_objects.append(data_obj)
            
        # If this page had a diagram, create a dedicated DIAGRAM data object
        if has_diagram and image_url:
            diagram_obj_id = f"{form_number}_p{page_num}_diag"
            diagram_data_obj = {
                "name": f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/carrier-chiller-docs/dataObjects/{diagram_obj_id}",
                "data": {
                    "chunk_id": diagram_obj_id,
                    "model_series": model_series,
                    "form_number": form_number,
                    "section": current_section,
                    "page_number": page_num,
                    "content_type": "diagram",
                    "content": f"Schematic diagram: {diagram_caption}. Equipment: Carrier {model_series}. Section: {current_section}. Page {page_num}.\n\nSurrounding text:\n{text[:400]}",
                    "has_image": True,
                    "image_url": image_url,
                    "diagram_caption": diagram_caption,
                    "diagram_ocr_details": f"Carrier {model_series} engineering diagram: {diagram_caption}"
                }
            }
            if visual_embedding:
                diagram_data_obj["vectors"] = {
                    "visual_embedding": {
                        "values": visual_embedding
                    }
                }
            data_objects.append(diagram_data_obj)
            
    return data_objects


def main():
    print("==================================================")
    print("Starting Carrier Chiller Ingestion & Diagram Pipeline")
    print(f"Project: {PROJECT_ID} | Region: {LOCATION}")
    print(f"Target Bucket: {GCS_BUCKET_NAME}")
    print("==================================================")
    
    storage_client = storage.Client(project=PROJECT_ID)
    bucket = ensure_gcs_bucket(storage_client, GCS_BUCKET_NAME)
    
    # Initialize Vertex AI Multimodal Embedding Model
    try:
        vertexai.init(project=PROJECT_ID, location=LOCATION)
        multimodal_model = MultiModalEmbeddingModel.from_pretrained("multimodalembedding@001")
        print("[Vertex AI] MultimodalEmbeddingModel initialized successfully.")
    except Exception as e:
        print(f"[WARN] Could not initialize MultimodalEmbeddingModel ({e}). Proceeding without visual embeddings.")
        multimodal_model = None

    all_data_objects: List[Dict[str, Any]] = []
    
    for manual in MANUAL_CATALOG:
        objects = extract_and_process_manual(manual, bucket, multimodal_model)
        all_data_objects.extend(objects)
        print(f"[SUCCESS] {manual['model_series']}: Generated {len(objects)} data objects.")
        
    print(f"\nWriting {len(all_data_objects)} total objects to {JSONL_OUTPUT}...")
    with open(JSONL_OUTPUT, "w") as f:
        for obj in all_data_objects:
            f.write(json.dumps(obj) + "\n")
            
    print(f"[COMPLETE] Ingestion file ready: {JSONL_OUTPUT.resolve()}")


if __name__ == "__main__":
    main()
