"""
Production Ingestion Engine: Google Cloud Document AI Layout Parser + Vector Search 2.0.
Uses Document AI Layout Parser (v1.0) to parse technical chiller manuals into structured layout blocks,
identifies electrical figures, crops 300 DPI schematics to Cloud Storage, and generates Vector Search 2.0 DataObjects.
"""

import os
import sys
import re
import json
import io
import time
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional

from google.cloud import documentai
from google.cloud import storage
from google.protobuf.json_format import MessageToDict
import vertexai
from vertexai.vision_models import MultiModalEmbeddingModel, Image as VertexImage
from google.cloud import vectorsearch_v1beta
import pypdf
import pypdfium2 as pdfium
from PIL import Image

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "genai-demos-391416")
LOCATION = os.getenv("GOOGLE_CLOUD_REGION", "us-central1")
DOCAI_PROCESSOR_NAME = os.getenv(
    "DOCAI_PROCESSOR_NAME",
    "projects/genai-demos-391416/locations/us/processors/7e751de2124d0246"
)
ASSETS_BUCKET = os.getenv("CARRIER_ASSETS_BUCKET", f"{PROJECT_ID}-carrier-assets")
COLLECTION_NAME = os.getenv("VECTOR_SEARCH_COLLECTION", "carrier-chiller-docs")

FIGURE_PATTERN = re.compile(r"(Fig(?:ure)?\.?\s*\d+\s*[-–—]\s*[^.\n\r]+)", re.IGNORECASE)

MANUAL_CATALOG = [
    {"model_series": "19XR", "form_number": "19XR-CLT-9T", "filename": "19XR-CLT-9T.pdf"},
    {"model_series": "23XRV", "form_number": "23XRV-3T", "filename": "23XRV-3T.pdf"},
    {"model_series": "30HX", "form_number": "30HX-2T", "filename": "30HX-2T.pdf"},
    {"model_series": "30RC", "form_number": "30RC-101T", "filename": "30RC-101T.pdf"},
    {"model_series": "30XV", "form_number": "30XV-6T", "filename": "30XV-6T.pdf"},
]


class DocumentAIIngestionEngine:
    """Enterprise Document AI Ingestion Engine using Google Cloud Document AI Layout Parser."""

    def __init__(
        self,
        project_id: str = PROJECT_ID,
        location: str = LOCATION,
        processor_name: str = DOCAI_PROCESSOR_NAME,
        assets_bucket: str = ASSETS_BUCKET,
        collection_name: str = COLLECTION_NAME,
    ):
        self.project_id = project_id
        self.location = location
        self.processor_name = processor_name
        self.assets_bucket_name = assets_bucket
        self.collection_name = collection_name

        self.docai_client = documentai.DocumentProcessorServiceClient()
        self.storage_client = storage.Client(project=self.project_id)
        self.assets_bucket = self.storage_client.bucket(self.assets_bucket_name)

        # Initialize Vertex AI for multimodal vectors
        try:
            vertexai.init(project=self.project_id, location=self.location)
            self.multimodal_model = MultiModalEmbeddingModel.from_pretrained("multimodalembedding@001")
            print("[Vertex AI] MultimodalEmbeddingModel loaded successfully.")
        except Exception as e:
            print(f"[WARN] Multimodal embedding unavailable ({e}). Continuing with text vectors only.")
            self.multimodal_model = None

    def parse_pdf_bytes_docai(self, pdf_bytes: bytes) -> Dict[str, Any]:
        """Invokes Document AI Layout Parser on a slice or document."""
        raw_document = documentai.RawDocument(content=pdf_bytes, mime_type="application/pdf")
        request = documentai.ProcessRequest(name=self.processor_name, raw_document=raw_document)
        response = self.docai_client.process_document(request=request)
        return MessageToDict(response._pb)

    def process_manual(
        self,
        pdf_path: Path,
        model_series: str,
        form_number: str,
        max_pages: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Processes a local PDF manual using Document AI Layout Parser and renders 300 DPI schematics."""
        print(f"\n==================================================")
        print(f"[DocAI] Processing {model_series} ({pdf_path.name}) via Layout Parser...")
        print(f"==================================================")

        reader = pypdf.PdfReader(str(pdf_path))
        pdf_document = pdfium.PdfDocument(str(pdf_path))
        total_pages = min(len(reader.pages), max_pages) if max_pages else len(reader.pages)

        data_objects: List[Dict[str, Any]] = []
        current_section = "GENERAL"

        for page_idx in range(total_pages):
            page_num = page_idx + 1
            
            # Slice single page for Document AI Layout Parser
            writer = pypdf.PdfWriter()
            writer.add_page(reader.pages[page_idx])
            slice_buf = io.BytesIO()
            writer.write(slice_buf)
            page_bytes = slice_buf.getvalue()

            try:
                layout_dict = self.parse_pdf_bytes_docai(page_bytes)
                blocks = layout_dict.get("document", {}).get("documentLayout", {}).get("blocks", [])
            except Exception as e:
                print(f"[WARN] Page {page_num} DocAI parse failed: {e}. Falling back to reader text.")
                blocks = []

            # Extract text blocks and detect section headers & figures
            page_text_lines = []
            has_diagram = False
            diagram_caption = ""

            for b in blocks:
                if "textBlock" in b:
                    tb = b["textBlock"]
                    t_type = tb.get("type", "")
                    text_val = tb.get("text", "").strip()
                    if not text_val:
                        continue

                    page_text_lines.append(text_val)

                    # Section header detection
                    if t_type in ("header", "heading-1", "heading-2"):
                        clean_hdr = text_val.upper()
                        if any(sec in clean_hdr for sec in ["CONTROLS", "TROUBLESHOOTING", "WIRING", "START-UP", "SAFETY", "SERVICE"]):
                            if len(clean_hdr) < 70:
                                current_section = clean_hdr

                    # Detect Figure Caption
                    fig_match = FIGURE_PATTERN.search(text_val)
                    if fig_match and not has_diagram:
                        has_diagram = True
                        diagram_caption = fig_match.group(1).strip()

            page_full_text = "\n\n".join(page_text_lines)
            if not page_full_text:
                # Fallback to local text extraction if page had no text blocks
                page_full_text = reader.pages[page_idx].extract_text() or ""
                fig_match = FIGURE_PATTERN.search(page_full_text)
                if fig_match and not has_diagram:
                    has_diagram = True
                    diagram_caption = fig_match.group(1).strip()

            image_url = ""
            visual_vec = None

            # Render schematic at 300 DPI if diagram was detected
            if has_diagram:
                try:
                    pdf_page = pdf_document[page_idx]
                    pil_image = pdf_page.render(scale=3.0).to_pil()

                    clean_fig = re.sub(r"[^a-zA-Z0-9_-]", "_", diagram_caption)[:40]
                    gcs_blob_name = f"diagrams/{model_series}/{form_number}_p{page_num}_{clean_fig}.webp"
                    
                    buf = io.BytesIO()
                    pil_image.save(buf, format="WEBP", quality=85)
                    webp_bytes = buf.getvalue()

                    blob = self.assets_bucket.blob(gcs_blob_name)
                    blob.cache_control = "public, max-age=86400, immutable"
                    blob.upload_from_string(webp_bytes, content_type="image/webp")
                    image_url = f"https://storage.googleapis.com/{self.assets_bucket_name}/{gcs_blob_name}"

                    if self.multimodal_model:
                        v_img = VertexImage(webp_bytes)
                        emb = self.multimodal_model.get_embeddings(
                            image=v_img,
                            contextual_text=f"Carrier {model_series} {diagram_caption}"
                        )
                        if emb.image_embedding:
                            visual_vec = list(emb.image_embedding)

                    diag_id = f"{form_number}_p{page_num}_diag"
                    diag_obj = {
                        "name": f"projects/{self.project_id}/locations/{self.location}/collections/{self.collection_name}/dataObjects/{diag_id}",
                        "data": {
                            "chunk_id": diag_id,
                            "model_series": model_series,
                            "form_number": form_number,
                            "section": current_section,
                            "page_number": page_num,
                            "content_type": "diagram",
                            "content": f"Schematic diagram: {diagram_caption}. Equipment: Carrier {model_series}. Section: {current_section}. Page {page_num}.\n\nSurrounding text:\n{page_full_text[:400]}",
                            "has_image": True,
                            "image_url": image_url,
                            "diagram_caption": diagram_caption,
                            "diagram_ocr_details": f"Carrier {model_series} engineering diagram: {diagram_caption}"
                        }
                    }
                    if visual_vec:
                        diag_obj["vectors"] = {"visual_embedding": {"values": visual_vec}}
                    data_objects.append(diag_obj)
                except Exception as ex:
                    print(f"[WARN] Error rendering diagram on page {page_num}: {ex}")

            # Text Chunking (800-1200 characters)
            paragraphs = [p.strip() for p in page_full_text.split("\n\n") if p.strip()]
            chunk_buffer = ""
            chunk_idx = 1
            for para in paragraphs:
                if len(chunk_buffer) + len(para) > 1000 and len(chunk_buffer) > 200:
                    c_id = f"{form_number}_p{page_num}_c{chunk_idx}"
                    data_objects.append({
                        "name": f"projects/{self.project_id}/locations/{self.location}/collections/{self.collection_name}/dataObjects/{c_id}",
                        "data": {
                            "chunk_id": c_id,
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
                    })
                    chunk_buffer = para + "\n\n"
                    chunk_idx += 1
                else:
                    chunk_buffer += para + "\n\n"

            if chunk_buffer.strip():
                c_id = f"{form_number}_p{page_num}_c{chunk_idx}"
                data_objects.append({
                    "name": f"projects/{self.project_id}/locations/{self.location}/collections/{self.collection_name}/dataObjects/{c_id}",
                    "data": {
                        "chunk_id": c_id,
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
                })

        print(f"[DocAI] {model_series}: Created {len(data_objects)} data objects across {total_pages} pages.")
        return data_objects

    def upload_to_vector_search(self, data_objects: List[Dict[str, Any]], batch_size: int = 50) -> int:
        """Batch uploads data objects into the Vector Search 2.0 Collection."""
        client = vectorsearch_v1beta.VectorSearchServiceClient()
        parent = f"projects/{self.project_id}/locations/{self.location}/collections/{self.collection_name}"

        total_loaded = 0
        for i in range(0, len(data_objects), batch_size):
            batch = data_objects[i:i + batch_size]
            req = vectorsearch_v1beta.BatchCreateDataObjectsRequest(
                parent=parent,
                requests=[
                    vectorsearch_v1beta.CreateDataObjectRequest(
                        parent=parent,
                        data_object_id=obj["data"]["chunk_id"],
                        data_object=vectorsearch_v1beta.DataObject(
                            data=obj["data"],
                            vectors=obj.get("vectors")
                        )
                    )
                    for obj in batch
                ]
            )
            client.batch_create_data_objects(request=req)
            total_loaded += len(batch)
            print(f"[VS 2.0] Uploaded {total_loaded}/{len(data_objects)} objects to collection {self.collection_name}")
        return total_loaded


def main():
    parser = argparse.ArgumentParser(description="Document AI Layout Parser Ingestion for Carrier Chillers")
    parser.add_argument("--pdf", type=str, help="Path to single Carrier PDF manual")
    parser.add_argument("--model", type=str, help="Model series (19XR, 23XRV, 30HX, 30RC, 30XV)")
    parser.add_argument("--form", type=str, help="Form number (e.g. 30XV-6T)")
    parser.add_argument("--all", action="store_true", help="Process all manuals in catalog")
    parser.add_argument("--pages", type=int, default=None, help="Limit number of pages for testing")
    parser.add_argument("--upload", action="store_true", help="Directly upload to Vector Search 2.0")
    args = parser.parse_args()

    engine = DocumentAIIngestionEngine()
    all_objects = []

    if args.all:
        for manual in MANUAL_CATALOG:
            p = Path("Input Documents") / manual["filename"]
            if p.exists():
                objs = engine.process_manual(p, manual["model_series"], manual["form_number"], max_pages=args.pages)
                all_objects.extend(objs)
    elif args.pdf:
        p = Path(args.pdf)
        model = args.model or "30XV"
        form = args.form or "30XV-6T"
        all_objects = engine.process_manual(p, model, form, max_pages=args.pages)
    else:
        print("Please provide --pdf <path> --model <series> or --all. Example: python ingestion/document_ai_ingestion.py --all --pages 5")
        sys.exit(1)

    print(f"\n[DONE] Successfully generated {len(all_objects)} Document AI DataObjects.")
    if args.upload:
        engine.upload_to_vector_search(all_objects)


if __name__ == "__main__":
    main()
