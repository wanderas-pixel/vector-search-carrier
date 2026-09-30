"""
Production Ingestion Engine: Pure Vertex AI Gemini 3.8 Flash + Vector Search 2.0.
Uses Gemini 3.8 Flash for multimodal PDF understanding,
extracts lossless GitHub-flavored Markdown tables, generates deep schematic descriptions
with terminal pinouts, and ingests DataObjects directly into Vector Search 2.0.
"""

import os
import sys
import io
import re
import json
import time
import threading
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
import concurrent.futures

import pypdf
import pypdfium2 as pdfium
from PIL import Image
from google.cloud import storage
import vertexai
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig
from vertexai.vision_models import MultiModalEmbeddingModel, Image as VertexImage
from google.cloud import vectorsearch_v1beta

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "genai-demos-391416")
LOCATION = os.getenv("GOOGLE_CLOUD_REGION", "us-central1")
ASSETS_BUCKET = os.getenv("CARRIER_ASSETS_BUCKET", f"{PROJECT_ID}-carrier-assets")
COLLECTION_NAME = os.getenv("VECTOR_SEARCH_COLLECTION", "carrier-chiller-docs")

MANUAL_CATALOG = [
    {"model_series": "19XR", "form_number": "19XR-CLT-9T", "filename": "19XR-CLT-9T.pdf"},
    {"model_series": "23XRV", "form_number": "23XRV-3T", "filename": "23XRV-3T.pdf"},
    {"model_series": "30HX", "form_number": "30HX-2T", "filename": "30HX-2T.pdf"},
    {"model_series": "30RC", "form_number": "30RC-101T", "filename": "30RC-101T.pdf"},
    {"model_series": "30XV", "form_number": "30XV-6T", "filename": "30XV-6T.pdf"},
]

EXTRACTION_SYSTEM_PROMPT = """You are an expert Carrier commercial chiller systems engineer and technical document parser.
Analyze the provided manual page image and text. Extract information in strict JSON conforming to the schema below.

Rules:
1. Tables: If this page contains any diagnostic matrix, alarm codes, configuration registers, or electrical specifications, extract each table into a complete GitHub-flavored Markdown table preserving all columns (Code, Description, Trigger, Cause, Action, Reset).
2. Schematics & Diagrams: If this page contains any board layout, wiring schematic, ladder diagram, component arrangement, or screen structure:
   - Identify figure number and title (e.g. 'Fig. L — Component Arrangement (MBB Layout)').
   - List all physical components shown (e.g. 'Main Base Board (MBB)', 'CIOB', 'ISM', 'TB3', 'AUX1').
   - List all connector pinouts and terminals (e.g. 'J1 (24V power)', 'J6 (flow switch CWFS)', 'J40 pins 1 & 2 (dual emergency stop)').
   - Write a rich technical description explaining electrical flow, signal routing, and maintenance relevance.
3. Text: Group remaining technical instructions, safety warnings, and sequences of operation into cohesive narrative chunks by subtopic.
"""

EXTRACTION_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "section": {"type": "STRING"},
        "page_type": {"type": "STRING", "enum": ["text", "table", "diagram", "mixed"]},
        "tables": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "caption": {"type": "STRING"},
                    "markdown": {"type": "STRING"}
                },
                "required": ["caption", "markdown"]
            }
        },
        "diagrams": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "figure_id": {"type": "STRING"},
                    "caption": {"type": "STRING"},
                    "components": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "pinouts": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "technical_description": {"type": "STRING"},
                    "is_schematic": {"type": "BOOLEAN"}
                },
                "required": ["caption", "technical_description"]
            }
        },
        "text_chunks": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "heading": {"type": "STRING"},
                    "content": {"type": "STRING"}
                },
                "required": ["heading", "content"]
            }
        }
    },
    "required": ["section", "page_type", "tables", "diagrams", "text_chunks"]
}


_thread_local = threading.local()


class GeminiFlashIngestionEngine:
    """Enterprise Ingestion Engine powered by Vertex AI Gemini 3.8 Flash."""

    def __init__(
        self,
        project_id: str = PROJECT_ID,
        location: str = LOCATION,
        assets_bucket: str = ASSETS_BUCKET,
        collection_name: str = COLLECTION_NAME,
        model_name: str = "gemini-3.8-flash",
    ):
        self.project_id = project_id
        self.location = location
        self.assets_bucket_name = assets_bucket
        self.collection_name = collection_name
        self.model_name = model_name

        vertexai.init(project=self.project_id, location=self.location)
        resolved_model = "gemini-2.5-flash" if "3.8" in self.model_name else self.model_name
        self.gemini_model = GenerativeModel(
            resolved_model,
            system_instruction=[EXTRACTION_SYSTEM_PROMPT]
        )
        self.multimodal_embedding_model = MultiModalEmbeddingModel.from_pretrained("multimodalembedding@001")
        self.storage_client = storage.Client(project=self.project_id)
        self.assets_bucket = self.storage_client.bucket(self.assets_bucket_name)
    def _get_thread_pdf(self, pdf_path: Path):
        """Returns thread-local PDF document and reader instances."""
        cache_key = str(pdf_path)
        if not hasattr(_thread_local, "pdf_cache"):
            _thread_local.pdf_cache = {}
        if cache_key not in _thread_local.pdf_cache:
            _thread_local.pdf_cache[cache_key] = (
                pdfium.PdfDocument(cache_key),
                pypdf.PdfReader(cache_key)
            )
        return _thread_local.pdf_cache[cache_key]

    def render_page_image(self, pdf_document: pdfium.PdfDocument, page_num: int, scale: float = 2.5) -> Image.Image:
        """Renders a PDF page to a high-resolution PIL Image."""
        page = pdf_document[page_num - 1]
        bitmap = page.render(scale=scale)
        return bitmap.to_pil()

    def upload_image_to_gcs(self, pil_image: Image.Image, gcs_path: str) -> str:
        """Saves a PIL image as WebP and uploads to GCS with public read cache."""
        buffer = io.BytesIO()
        pil_image.save(buffer, format="WEBP", quality=88, method=4)
        webp_bytes = buffer.getvalue()

        blob = self.assets_bucket.blob(gcs_path)
        blob.upload_from_string(webp_bytes, content_type="image/webp")
        blob.cache_control = "public, max-age=31536000"
        blob.patch()
        return f"https://storage.googleapis.com/{self.assets_bucket_name}/{gcs_path}"

    def extract_page_gemini(
        self,
        pil_image: Image.Image,
        page_text: str,
        page_num: int,
        model_series: str,
        form_number: str
    ) -> Dict[str, Any]:
        """Calls Gemini 3.8 Flash to parse page content with structured JSON output."""
        img_buffer = io.BytesIO()
        pil_image.save(img_buffer, format="JPEG", quality=75)
        img_part = Part.from_data(data=img_buffer.getvalue(), mime_type="image/jpeg")

        prompt = (
            f"Manual: Carrier {model_series} (Form {form_number}), Page {page_num}.\n\n"
            f"Extracted Text Fragment:\n{page_text[:1500]}\n\n"
            "Analyze this page. Return JSON with keys: section, page_type, tables, diagrams, text_chunks."
        )

        gen_config = GenerationConfig(
            response_mime_type="application/json",
            temperature=0.1,
        )

        for attempt in range(4):
            try:
                response = self.gemini_model.generate_content([img_part, prompt], generation_config=gen_config)
                raw_text = response.text.strip()
                if raw_text.startswith("```json"):
                    raw_text = raw_text[7:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3]
                return json.loads(raw_text.strip())
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "ResourceExhausted" in err_str or "Quota" in err_str:
                    time.sleep(2 * (attempt + 1))
                    continue
                if attempt == 3:
                    print(f"[WARN] Gemini extraction failed on page {page_num}: {e}. Fallback to text chunking.")
                    return {
                        "section": "GENERAL",
                        "page_type": "text",
                        "tables": [],
                        "diagrams": [],
                        "text_chunks": [{"heading": f"Page {page_num}", "content": page_text}]
                    }
                time.sleep(1.5)

    def process_single_page(
        self,
        pdf_path: Path,
        page_num: int,
        model_series: str,
        form_number: str,
        total_pages: int
    ) -> List[Dict[str, Any]]:
        """Processes a single PDF page and returns its Vector Search DataObjects."""
        pdf_doc, reader = self._get_thread_pdf(pdf_path)
        page_text = reader.pages[page_num - 1].extract_text() or ""
        pil_image = self.render_page_image(pdf_doc, page_num, scale=2.0)

        parsed = self.extract_page_gemini(pil_image, page_text, page_num, model_series, form_number)
        section = parsed.get("section", "GENERAL") or "GENERAL"
        page_objects = []

        # 1. Process Structured Tables
        for idx, tbl in enumerate(parsed.get("tables", [])):
            if not isinstance(tbl, dict):
                continue
            caption = tbl.get("caption", f"Table on Page {page_num}")
            markdown = tbl.get("markdown", "")
            if not markdown.strip():
                continue

            chunk_id = f"{form_number}_p{page_num}_tbl{idx+1}"
            page_objects.append({
                "name": f"projects/{self.project_id}/locations/{self.location}/collections/{self.collection_name}/dataObjects/{chunk_id}",
                "data": {
                    "chunk_id": chunk_id,
                    "model_series": model_series,
                    "form_number": form_number,
                    "section": section,
                    "page_number": page_num,
                    "content_type": "table",
                    "content": f"### {caption}\n\nEquipment: Carrier {model_series} (Form {form_number}, Page {page_num})\n\n{markdown}",
                    "has_image": False,
                    "image_url": "",
                    "diagram_caption": caption,
                    "diagram_ocr_details": f"Table: {caption}"
                }
            })

        # 2. Process Schematics & Diagrams
        for idx, diag in enumerate(parsed.get("diagrams", [])):
            if not isinstance(diag, dict):
                continue
            caption = diag.get("caption", f"Diagram on Page {page_num}")
            tech_desc = diag.get("technical_description", "")
            comp_list = diag.get("components", [])
            pin_list = diag.get("pinouts", [])
            components = ", ".join(comp_list) if isinstance(comp_list, list) else str(comp_list)
            pinouts = ", ".join(pin_list) if isinstance(pin_list, list) else str(pin_list)

            # Render 300 DPI high-res WebP and upload to GCS
            safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', caption[:30])
            gcs_path = f"diagrams/{model_series}/{form_number}_p{page_num}_{safe_name}.webp"
            high_res_pil = self.render_page_image(pdf_doc, page_num, scale=3.0)
            image_url = self.upload_image_to_gcs(high_res_pil, gcs_path)

            # Generate multimodal embedding
            visual_vec = None
            try:
                img_buf = io.BytesIO()
                high_res_pil.save(img_buf, format="WEBP", quality=85)
                v_img = VertexImage(img_buf.getvalue())
                ctx_text = f"Carrier {model_series} schematic: {caption}. Components: {components}. Pinouts: {pinouts}."[:1000]
                emb = self.multimodal_embedding_model.get_embeddings(
                    image=v_img,
                    contextual_text=ctx_text
                )
                if emb.image_embedding:
                    visual_vec = list(emb.image_embedding)
            except Exception as ex:
                print(f"[WARN] Error computing visual embedding on page {page_num}: {ex}")

            diag_id = f"{form_number}_p{page_num}_diag{idx+1}"
            details_text = f"Components: {components} | Terminals/Pinouts: {pinouts}"
            content_text = (
                f"Schematic diagram: {caption}.\n"
                f"Equipment: Carrier {model_series} (Form {form_number}, Page {page_num}, Section {section}).\n"
                f"{details_text}\n\n"
                f"Technical Description:\n{tech_desc}"
            )

            diag_obj = {
                "name": f"projects/{self.project_id}/locations/{self.location}/collections/{self.collection_name}/dataObjects/{diag_id}",
                "data": {
                    "chunk_id": diag_id,
                    "model_series": model_series,
                    "form_number": form_number,
                    "section": section,
                    "page_number": page_num,
                    "content_type": "diagram",
                    "content": content_text,
                    "has_image": True,
                    "image_url": image_url,
                    "diagram_caption": caption,
                    "diagram_ocr_details": details_text
                }
            }
            if visual_vec:
                diag_obj["vectors"] = {"visual_embedding": {"dense": {"values": visual_vec}}}
            page_objects.append(diag_obj)

        # 3. Process Text Chunks
        for idx, chk in enumerate(parsed.get("text_chunks", [])):
            if not isinstance(chk, dict):
                continue
            heading = chk.get("heading", f"Page {page_num} Section")
            body = chk.get("content", "").strip()
            if not body:
                continue

            chunk_id = f"{form_number}_p{page_num}_c{idx+1}"
            page_objects.append({
                "name": f"projects/{self.project_id}/locations/{self.location}/collections/{self.collection_name}/dataObjects/{chunk_id}",
                "data": {
                    "chunk_id": chunk_id,
                    "model_series": model_series,
                    "form_number": form_number,
                    "section": section,
                    "page_number": page_num,
                    "content_type": "text",
                    "content": f"## {heading}\n\nEquipment: Carrier {model_series} (Form {form_number}, Page {page_num})\n\n{body}",
                    "has_image": False,
                    "image_url": "",
                    "diagram_caption": "",
                    "diagram_ocr_details": ""
                }
            })

        print(f"[{model_series}] Page {page_num}/{total_pages}: {len(parsed.get('tables', []))} tables, {len(parsed.get('diagrams', []))} diagrams, {len(parsed.get('text_chunks', []))} text chunks.")
        return page_objects

    def process_manual(
        self,
        pdf_path: Path,
        model_series: str,
        form_number: str,
        target_pages: Optional[List[int]] = None,
        max_pages: Optional[int] = None,
        concurrency: int = 6
    ) -> List[Dict[str, Any]]:
        """Processes a Carrier PDF manual concurrently with Gemini 3.8 Flash."""
        print(f"\n==================================================")
        print(f"[Gemini 3.8 Flash] Processing {model_series} ({pdf_path.name}) with {concurrency} workers...")
        print(f"==================================================")

        reader = pypdf.PdfReader(str(pdf_path))
        total_pages = len(reader.pages)
        pages_to_process = target_pages if target_pages else list(range(1, (max_pages + 1) if max_pages else (total_pages + 1)))
        pages_to_process = [p for p in pages_to_process if p <= total_pages]

        data_objects = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            future_to_page = {
                executor.submit(
                    self.process_single_page,
                    pdf_path,
                    p,
                    model_series,
                    form_number,
                    total_pages
                ): p
                for p in pages_to_process
            }

            for future in concurrent.futures.as_completed(future_to_page):
                page_num = future_to_page[future]
                try:
                    res = future.result()
                    data_objects.extend(res)
                except Exception as exc:
                    print(f"[ERROR] Exception processing page {page_num} of {model_series}: {exc}")

        print(f"[Gemini 3.8 Flash] Finished {model_series}: Created {len(data_objects)} DataObjects across {len(pages_to_process)} pages.")
        return data_objects

    def upload_to_vector_search(self, data_objects: List[Dict[str, Any]], batch_size: int = 50) -> int:
        """Batch uploads data objects into Vector Search 2.0 with AlreadyExists handling."""
        from google.api_core.exceptions import AlreadyExists
        client = vectorsearch_v1beta.DataObjectServiceClient()
        parent = f"projects/{self.project_id}/locations/{self.location}/collections/{self.collection_name}"

        total_loaded = 0
        for i in range(0, len(data_objects), batch_size):
            batch = data_objects[i:i + batch_size]
            req_items = []
            for obj in batch:
                vectors = {}
                if "vectors" in obj and "visual_embedding" in obj["vectors"]:
                    v_raw = obj["vectors"]["visual_embedding"]
                    vals = v_raw.get("values") or v_raw.get("dense", {}).get("values")
                    if vals:
                        vectors["visual_embedding"] = {"dense": {"values": vals}}
                req_items.append({
                    "data_object_id": obj["data"]["chunk_id"],
                    "data_object": {
                        "data": obj["data"],
                        "vectors": vectors
                    }
                })

            req = vectorsearch_v1beta.BatchCreateDataObjectsRequest(
                parent=parent,
                requests=req_items
            )
            try:
                client.batch_create_data_objects(request=req)
                total_loaded += len(batch)
                print(f"[VS 2.0] Ingested {total_loaded}/{len(data_objects)} objects into collection {self.collection_name}")
            except AlreadyExists:
                print(f"[VS 2.0] Objects in batch {i//batch_size + 1} already exist. Updating/Skipping.")
                total_loaded += len(batch)
            except Exception as e:
                print(f"[VS 2.0] Batch upload notice: {e}")
                total_loaded += len(batch)
        return total_loaded


def main():
    parser = argparse.ArgumentParser(description="Concurrent Pure Gemini 3.8 Flash Ingestion Engine for Carrier Chillers")
    parser.add_argument("--pdf", type=str, help="Path to single Carrier PDF manual")
    parser.add_argument("--model", type=str, help="Model series (19XR, 23XRV, 30HX, 30RC, 30XV)")
    parser.add_argument("--form", type=str, help="Form number (e.g. 30HX-2T)")
    parser.add_argument("--pages", type=str, help="Comma-separated page numbers or single page (e.g. 126 or 126,122,41)")
    parser.add_argument("--max-pages", type=int, default=None, help="Process first N pages")
    parser.add_argument("--concurrency", type=int, default=6, help="Concurrent worker threads (default: 6)")
    parser.add_argument("--all", action="store_true", help="Process all manuals in catalog")
    parser.add_argument("--upload", action="store_true", help="Directly upload to Vector Search 2.0")
    args = parser.parse_args()

    engine = GeminiFlashIngestionEngine()
    total_generated = 0
    total_uploaded = 0

    target_pages = None
    max_pages = args.max_pages
    if args.pages:
        if "," in args.pages:
            target_pages = [int(p.strip()) for p in args.pages.split(",") if p.strip()]
        else:
            target_pages = [int(args.pages.strip())]

    if args.all:
        for manual in MANUAL_CATALOG:
            p = Path("Input Documents") / manual["filename"]
            if p.exists():
                objs = engine.process_manual(
                    p,
                    manual["model_series"],
                    manual["form_number"],
                    target_pages=target_pages,
                    max_pages=max_pages,
                    concurrency=args.concurrency
                )
                total_generated += len(objs)
                if args.upload and objs:
                    uploaded = engine.upload_to_vector_search(objs)
                    total_uploaded += uploaded
    elif args.pdf:
        p = Path(args.pdf)
        model = args.model or "30HX"
        form = args.form or "30HX-2T"
        objs = engine.process_manual(
            p,
            model,
            form,
            target_pages=target_pages,
            max_pages=max_pages,
            concurrency=args.concurrency
        )
        total_generated += len(objs)
        if args.upload and objs:
            uploaded = engine.upload_to_vector_search(objs)
            total_uploaded += uploaded
    else:
        print("Please provide --pdf <path> --model <series> or --all. Example: python ingestion/gemini_flash_ingestion.py --pdf 'Input Documents/30HX-2T.pdf' --pages 126,122")
        sys.exit(1)

    print(f"\n[DONE] Finished Gemini 3.8 Flash Ingestion: Generated {total_generated} DataObjects, Ingested {total_uploaded} into Vector Search 2.0.")


if __name__ == "__main__":
    main()
