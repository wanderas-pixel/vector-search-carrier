"""
Carrier HVAC Technical Specialist - FastAPI Backend Service.
Connects the React 19 Frontend with:
- Google ADK 2.0 Carrier Agent
- Vector Search 2.0 Collection (carrier-chiller-docs)
- Google Cloud Logging Audit Telemetry
- Precise Perceived Turnaround Latency Tracker
"""

import os
import sys
import time
import json
import uuid
import re
from typing import Optional, List, Dict, Any
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import Response, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from google.cloud import storage

# Ensure carrier-agent path is in sys.path
CARRIER_AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "carrier-agent"))
if CARRIER_AGENT_DIR not in sys.path:
    sys.path.insert(0, CARRIER_AGENT_DIR)

GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "genai-demos-391416-carrier-assets")
_storage_client = None

def _get_gcs_blob(file_path: str):
    global _storage_client
    if _storage_client is None:
        _storage_client = storage.Client()
    bucket = _storage_client.bucket(GCS_BUCKET_NAME)
    return bucket.blob(file_path)

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from google.cloud import logging as cloud_logging
from app.agent import root_agent
from app.tools import carrier_visual_search, carrier_knowledge_search, carrier_alarm_lookup, _get_multimodal_model, _search_client, COLLECTION_NAME

# Cloud Logging Client
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "genai-demos-391416")
try:
    _logging_client = cloud_logging.Client(project=PROJECT_ID)
    _api_logger = _logging_client.logger("carrier-api-server")
except Exception as e:
    _api_logger = None

app = FastAPI(
    title="Carrier HVAC Engineering Specialist API",
    description="Multimodal Chiller RAG & Diagnostic Agent API",
    version="2.0.0"
)

# Enable CORS for Vite frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.session_factory import get_session_service

# Session management for ADK (Production Distributed or Local Dev)
session_service = get_session_service()
runners: Dict[str, Runner] = {}

class ChatRequest(BaseModel):
    message: str = Field(..., description="User query or troubleshooting prompt")
    model_series: Optional[str] = Field(None, description="Optional model filter (19XR, 23XRV, 30HX, 30RC, 30XV)")
    session_id: Optional[str] = Field(None, description="Active session ID")
    client_send_time_ms: Optional[float] = Field(None, description="performance.now() timestamp when user clicked Send")

class ToolExecutionInfo(BaseModel):
    tool_name: str
    args: Dict[str, Any]
    latency_ms: float

class ChatResponse(BaseModel):
    session_id: str
    response: str
    tools_used: List[ToolExecutionInfo]
    server_latency_ms: float
    network_latency_est_ms: float
    turnaround_latency_ms: Optional[float] = None


@app.get("/api/health")
def health():
    return {
        "status": "healthy",
        "project_id": PROJECT_ID,
        "region": "us-central1",
        "agent": "carrier_chiller_specialist",
        "vector_search_collection": "carrier-chiller-docs",
        "supported_models": ["19XR", "23XRV", "30HX", "30RC", "30XV"]
    }


@app.get("/api/models")
def get_supported_models():
    return [
        {
            "series": "19XR",
            "name": "AquaEdge® 19XR Hermetic Centrifugal Liquid Chiller",
            "cooling_capacity": "200 to 3000 Tons",
            "manual_form": "19XR-CLT-9T",
            "refrigerant": "R-134a / R-513A",
            "compressor": "Semi-Hermetic Centrifugal Single-Stage Compressor",
            "description": "High-efficiency centrifugal chiller designed for large commercial, hospital, and district cooling systems.",
            "sample_questions": [
                "What is the recommended annual oil filter replacement procedure for the 19XR?",
                "What are the high-lift compressor startup limits on the 19XR?",
                "Show the oil pump wiring diagram and terminal block connections for 19XR."
            ]
        },
        {
            "series": "23XRV",
            "name": "AquaEdge® 23XRV Variable-Speed Water-Cooled Screw Chiller",
            "cooling_capacity": "250 to 550 Tons",
            "manual_form": "23XRV-14T",
            "refrigerant": "R-134a / R-513A",
            "compressor": "FoxStream™ Twin-Rotor Tri-Rotor Screw with integrated VFD",
            "description": "World's first integrated variable-speed, water-cooled screw chiller featuring ultra-quiet operation.",
            "sample_questions": [
                "What are the VFD DC bus pre-charge troubleshooting steps on 23XRV?",
                "What is the sensor thermistor resistance curve for 23XRV cooler entering fluid?",
                "Show the refrigerant flow schematic for 23XRV economizer circuit."
            ]
        },
        {
            "series": "30HX",
            "name": "AquaForce® 30HX Water-Cooled Condenserless Screw Chiller",
            "cooling_capacity": "75 to 265 Tons",
            "manual_form": "30HX-2T",
            "refrigerant": "R-134a",
            "compressor": "06N Semi-Hermetic Twin Screw Compressor",
            "description": "Compact footprint design suitable for retrofits with dual independent refrigerant circuits.",
            "sample_questions": [
                "What does alarm code T051 indicate on the 30HX Navigator?",
                "What are the CPM board S2/S3 DIP switch settings for compressor A1 vs B1?",
                "Explain the Wye-Delta starter contactor transition sequence on 30HX."
            ]
        },
        {
            "series": "30RC",
            "name": "AquaForce® 30RC Air-Cooled Scroll Chiller with Greenspeed® Intelligence",
            "cooling_capacity": "60 to 150 Tons",
            "manual_form": "30RC-101T",
            "refrigerant": "Puron Advance™ (R-32, A2L Mildly Flammable)",
            "compressor": "Variable-Speed Scroll Compressors",
            "description": "Next-generation low-GWP air-cooled chiller optimized with variable-speed ECM condenser fans.",
            "sample_questions": [
                "What are the mandatory A2L safety and leak detection protocols for 30RC servicing?",
                "What are the maximum water loop glycol concentration limits for 30RC?",
                "Show Fig. 48 Operating Envelope schematic for 30RC."
            ]
        },
        {
            "series": "30XV",
            "name": "AquaForce® 30XV Variable-Speed Air-Cooled Screw Chiller",
            "cooling_capacity": "140 to 500 Tons",
            "manual_form": "30XV-6T",
            "refrigerant": "R-134a / R-513A",
            "compressor": "06T Twin-Rotor Screw with dedicated Danfoss/Carrier VFD",
            "description": "Industry benchmark in full-load and part-load efficiency with Tier 4 low sound aerodynamics.",
            "sample_questions": [
                "What is the terminal pinout for the Dual Emergency Stop on CIOB J40?",
                "How do you troubleshoot VFD Earth Fault alarm 014 on 30XV?",
                "Show Fig. 51 Alarm Routing Control schematic for 30XV."
            ]
        }
    ]


def _determine_effective_prompt(message: str, model_series: Optional[str]) -> str:
    """Intelligently resolves target chiller model, allowing in-prompt model mentions to override dropdown."""
    detected_model = None
    for m in ["19XR", "23XRV", "30HX", "30RC", "30XV"]:
        if re.search(rf"\b{m}\b", message, re.IGNORECASE):
            detected_model = m
            break

    target_model = detected_model or (model_series if model_series and model_series != "All Models" else None)
    if target_model:
        return f"[Chiller Model: Carrier {target_model}]\n{message}"
    return message


def _clean_markdown_text(text: str) -> str:
    """Sanitizes merged markdown table headers, data rows, repetitive ASCII dashes, and auto-embeds image URLs."""
    if not text:
        return ""
    # 1. Convert any text image links or bullet URLs to markdown image syntax
    # E.g. "- Image URL: http..." or "- **Image URL**: http..." -> "\n\n![Carrier Technical Schematic](http...)\n\n"
    text = re.sub(
        r'(?:-\s*)?(?:\*\*)?Image URL(?:\*\*)?:\s*\[?(https?://[^\s\)]+(?:/api/image/|\.webp|\.png|\.jpg|\.jpeg)[^\s\)]*)\]?',
        r'\n\n![Carrier Technical Schematic](\1)\n\n',
        text,
        flags=re.IGNORECASE
    )
    # Convert non-image markdown links pointing to diagrams: [Caption](http://.../api/image/...webp) -> ![Caption](http://.../api/image/...webp)
    text = re.sub(
        r'(^|[^!])\[([^\]]+)\]\((https?://[^\s\)]+(?:/api/image/|\.webp|\.png|\.jpg|\.jpeg)[^\s\)]*)\)',
        r'\1\n\n![\2](\3)\n\n',
        text
    )
    # If an image URL is on a line by itself
    text = re.sub(
        r'(^|\n)(https?://[^\s\)]+/api/image/[^\s\)]+\.(?:webp|png|jpg|jpeg))(\n|$)',
        r'\1\n![Carrier Technical Schematic](\2)\n\3',
        text,
        flags=re.IGNORECASE
    )
    # 2. Separate merged table rows and delimiters (e.g. "| |:---" or "| | Alm-" or "| |")
    text = re.sub(r'\|\s*\|', '|\n|', text)
    # 3. Remove lines with 6 or more dashes/hyphens that were output as ASCII borders
    text = re.sub(r'^[ \t]*[-=]{6,}[ \t]*$', '', text, flags=re.MULTILINE)
    # 4. Collapse repeated horizontal rule markers (---)
    text = re.sub(r'(?:^[ \t]*---[ \t]*$\n?){2,}', '---\n', text, flags=re.MULTILINE)
    # 5. Remove blank lines between table rows (tables require adjacent rows)
    text = re.sub(r'\|\s*\n\s*\n\s*\|', '|\n|', text)
    text = re.sub(r'\|\s*\n\s*\n\s*\|', '|\n|', text)
    # 6. Ensure citations that are glued together on one line are split cleanly onto their own lines
    text = re.sub(r'(\[[^\]]+\])\s*(?=\[[^\]]+\])', r'\1\n', text)
    # 7. Ensure blank line before citations at end of table
    text = re.sub(r'(\|[^\n]+\|)\s*(\[[A-Z])', r'\1\n\n\2', text)
    # 8. Ensure standalone images have blank lines around them
    text = re.sub(r'([^\n])\n*(!\[[^\]]*\]\([^\)]+\))\n*([^\n])', r'\1\n\n\2\n\n\3', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    server_start_t = time.time()
    
    # Initialize or retrieve multi-turn conversational session
    session_id = req.session_id or f"sess_{uuid.uuid4().hex[:12]}"
    session = None
    try:
        session = await session_service.get_session(
            app_name="carrier_agent_app",
            user_id="field_engineer",
            session_id=session_id
        )
    except Exception as e:
        print(f"Session retrieval error: {e}")
        session = None

    if not session:
        session = await session_service.create_session(
            app_name="carrier_agent_app",
            user_id="field_engineer",
            session_id=session_id
        )

    runner = Runner(agent=root_agent, session_service=session_service, app_name="carrier_agent_app")

    # Format user prompt with intelligent model resolution
    effective_prompt = _determine_effective_prompt(req.message, req.model_series)

    tools_used: List[ToolExecutionInfo] = []
    final_text_parts: List[str] = []

    try:
        async for event in runner.run_async(
            session_id=session.id,
            user_id="field_engineer",
            new_message=types.Content(
                role="user",
                parts=[types.Part.from_text(text=effective_prompt)]
            )
        ):
            if hasattr(event, "content") and event.content:
                has_call = any(getattr(p, "function_call", None) is not None for p in event.content.parts)
                for part in event.content.parts:
                    if getattr(part, "function_call", None):
                        call = part.function_call
                        tools_used.append(ToolExecutionInfo(
                            tool_name=call.name,
                            args=dict(call.args) if call.args else {},
                            latency_ms=0.0
                        ))
                    elif getattr(part, "text", None) and not has_call:
                        final_text_parts.append(part.text)

        server_latency_ms = (time.time() - server_start_t) * 1000
        response_text = "".join(final_text_parts)

        # Rewrite GCS bucket URLs to local proxy so they load instantly without permission issues
        gcs_prefix = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/"
        proxy_prefix = "http://localhost:8000/api/image/"
        response_text = response_text.replace(gcs_prefix, proxy_prefix)
        response_text = _clean_markdown_text(response_text)

        # Calculate estimated network transit if client provided performance.now()
        network_latency_est_ms = 0.0

        # Emit audit entry to Cloud Logging
        if _api_logger:
            try:
                _api_logger.log_struct({
                    "service": "carrier-api-server",
                    "event": "CHAT_COMPLETED",
                    "session_id": session_id,
                    "model_series": req.model_series,
                    "query": req.message,
                    "server_latency_ms": round(server_latency_ms, 2),
                    "tools_count": len(tools_used),
                    "tools_list": [t.tool_name for t in tools_used]
                }, severity="INFO")
            except Exception as e:
                print(f"Logging error: {e}")

        return ChatResponse(
            session_id=session.id,
            response=response_text,
            tools_used=tools_used,
            server_latency_ms=round(server_latency_ms, 1),
            network_latency_est_ms=round(network_latency_est_ms, 1)
        )

    except Exception as e:
        server_latency_ms = (time.time() - server_start_t) * 1000
        if _api_logger:
            _api_logger.log_struct({
                "service": "carrier-api-server",
                "event": "CHAT_ERROR",
                "session_id": session_id,
                "error": str(e),
                "server_latency_ms": round(server_latency_ms, 2)
            }, severity="ERROR")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    server_start_t = time.time()

    # Initialize or retrieve multi-turn conversational session
    session_id = req.session_id or f"sess_{uuid.uuid4().hex[:12]}"
    session = None
    try:
        session = await session_service.get_session(
            app_name="carrier_agent_app",
            user_id="field_engineer",
            session_id=session_id
        )
    except Exception as e:
        print(f"Session retrieval error: {e}")
        session = None

    if not session:
        session = await session_service.create_session(
            app_name="carrier_agent_app",
            user_id="field_engineer",
            session_id=session_id
        )

    runner = Runner(agent=root_agent, session_service=session_service, app_name="carrier_agent_app")

    # Format user prompt with intelligent model resolution
    effective_prompt = _determine_effective_prompt(req.message, req.model_series)

    async def event_generator():
        tools_used: List[Dict[str, Any]] = []
        try:
            # Send initial session confirmation
            yield f"data: {json.dumps({'type': 'init', 'session_id': session.id})}\n\n"

            async for event in runner.run_async(
                session_id=session.id,
                user_id="field_engineer",
                new_message=types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=effective_prompt)]
                )
            ):
                if hasattr(event, "content") and event.content:
                    has_call = any(getattr(p, "function_call", None) is not None for p in event.content.parts)
                    for part in event.content.parts:
                        call = getattr(part, "function_call", None)
                        if call:
                            t_info = {
                                "tool_name": call.name,
                                "args": dict(call.args) if hasattr(call, "args") and call.args else {},
                                "latency_ms": 0.0
                            }
                            tools_used.append(t_info)
                            yield f"data: {json.dumps({'type': 'tool_call', 'tool_name': call.name})}\n\n"

                        text = getattr(part, "text", None)
                        if text and not has_call:
                            # Rewrite GCS storage URLs to local image proxy on the fly
                            clean_text = text.replace(
                                "https://storage.googleapis.com/genai-demos-391416-carrier-assets/",
                                "http://localhost:8000/api/image/"
                            )
                            yield f"data: {json.dumps({'type': 'token', 'content': clean_text})}\n\n"

            server_duration_ms = round((time.time() - server_start_t) * 1000, 1)

            # Log audit event
            if _api_logger:
                try:
                    _api_logger.log_struct({
                        "service": "carrier-api-server",
                        "event": "CHAT_STREAM_COMPLETED",
                        "session_id": session.id,
                        "model_series": req.model_series,
                        "query": req.message,
                        "server_latency_ms": server_duration_ms,
                        "tools_count": len(tools_used),
                        "tools_list": [t["tool_name"] for t in tools_used]
                    }, severity="INFO")
                except Exception as e:
                    print(f"Logging error: {e}")

            yield f"data: {json.dumps({'type': 'done', 'session_id': session.id, 'tools_used': tools_used, 'server_latency_ms': server_duration_ms})}\n\n"

        except Exception as e:
            print(f"Streaming error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/api/visual-search")
async def visual_search(
    file: Optional[UploadFile] = File(None),
    description: Optional[str] = Form(None),
    model_series: Optional[str] = Form(None)
):
    """Direct visual schematic search."""
    start_t = time.time()
    model_series = model_series.strip().upper() if model_series and model_series != "ALL MODELS" else ""
    
    if not file and not description:
        raise HTTPException(status_code=400, detail="Must provide either an image file or a description.")

    from google.cloud import vectorsearch_v1beta
    filt = {"model_series": {"$eq": model_series}} if model_series else None

    try:
        model = _get_multimodal_model()
        if file:
            contents = await file.read()
            from vertexai.vision_models import Image as VertexImage
            v_img = VertexImage(contents)
            v_emb = model.get_embeddings(image=v_img)
            query_vector = list(v_emb.image_embedding)
        else:
            v_emb = model.get_embeddings(contextual_text=f"Carrier Chiller schematic: {description}")
            query_vector = list(v_emb.text_embedding)

        req = vectorsearch_v1beta.SearchDataObjectsRequest(
            parent=COLLECTION_NAME,
            vector_search=vectorsearch_v1beta.VectorSearch(
                search_field="visual_embedding",
                vector={"values": query_vector},
                filter=filt,
                top_k=6,
                output_fields=vectorsearch_v1beta.OutputFields(
                    data_fields=["chunk_id", "model_series", "form_number", "page_number", "diagram_caption", "image_url", "content"]
                )
            )
        )

        response = list(_search_client.search_data_objects(req))
        latency_ms = (time.time() - start_t) * 1000

        diagrams = []
        for r in response:
            d = dict(r.data_object.data)
            img_url = d.get("image_url") or ""
            img_url = img_url.replace(f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/", "http://localhost:8000/api/image/")
            diagrams.append({
                "chunk_id": d.get("chunk_id"),
                "model_series": d.get("model_series"),
                "form_number": d.get("form_number"),
                "page_number": d.get("page_number"),
                "caption": d.get("diagram_caption"),
                "image_url": img_url,
                "context_snippet": str(d.get("content", ""))[:250]
            })

        return {
            "query_type": "image_upload" if file else "text_description",
            "latency_ms": round(latency_ms, 1),
            "results_count": len(diagrams),
            "diagrams": diagrams
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.api_route("/api/image/{file_path:path}", methods=["GET", "HEAD"])
async def get_diagram_image(file_path: str):
    """Proxy diagram image from GCS bucket with browser caching headers."""
    try:
        blob = _get_gcs_blob(file_path)
        if not blob.exists():
            raise HTTPException(status_code=404, detail="Diagram not found")
        content = blob.download_as_bytes()
        media_type = "image/webp" if file_path.endswith(".webp") else "image/png"
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Cache-Control": "public, max-age=86400, immutable",
                "Access-Control-Allow-Origin": "*",
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/logs/recent")
def get_recent_logs(limit: int = 15):
    """Retrieves recent structured audit entries from Google Cloud Logging."""
    try:
        entries = []
        if _logging_client:
            logger = _logging_client.logger("carrier-agent-audit")
            for entry in logger.list_entries(max_results=limit):
                entries.append({
                    "timestamp": entry.timestamp.isoformat() if entry.timestamp else "",
                    "severity": entry.severity,
                    "payload": entry.payload
                })
        return {"count": len(entries), "logs": entries}
    except Exception as e:
        return {"count": 0, "logs": [], "error": str(e)}


# Static file serving for single-container production deployment on Cloud Run
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="static_assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api"):
            raise HTTPException(status_code=404, detail="API route not found")
        index_file = FRONTEND_DIST / "index.html"
        return FileResponse(str(index_file))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("backend.server:app", host="0.0.0.0", port=port, reload=True)
