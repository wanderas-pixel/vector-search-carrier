"""
Carrier Chiller Engineering Agent Tools.
Provides Agent Retrieval tools powered by Google Cloud Vector Search 2.0:
- carrier_knowledge_search (Unified Hybrid search: dense semantic + BM25 lexical with dynamic RRF ranking & alarm fast-path)
- carrier_visual_search (Multimodal visual vector search)
- carrier_alarm_lookup (Legacy alias delegating to carrier_knowledge_search)

All tools emit structured JSON audit telemetry to Google Cloud Logging.
"""

import os
import time
import json
import re
from typing import Optional, List, Dict, Any

from google.protobuf.struct_pb2 import Struct
from google.cloud import vectorsearch_v1beta
from google.cloud import logging as cloud_logging
import vertexai
from vertexai.vision_models import MultiModalEmbeddingModel, Image as VertexImage

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "genai-demos-391416")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
COLLECTION_NAME = f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/carrier-chiller-docs"


def _make_field_filter(field: str, value: str) -> Optional[Struct]:
    """Constructs a raw protobuf Struct filter to prevent proto-plus dropping '$' keys."""
    if not value:
        return None
    s = Struct()
    inner = Struct()
    inner.fields["$eq"].string_value = value
    s.fields[field].struct_value.CopyFrom(inner)
    return s

# Initialize Cloud Logging client and logger
try:
    _logging_client = cloud_logging.Client(project=PROJECT_ID)
    _audit_logger = _logging_client.logger("carrier-agent-audit")
except Exception as e:
    _audit_logger = None

# Initialize Vector Search 2.0 Search Client
_search_client = vectorsearch_v1beta.DataObjectSearchServiceClient()

# Initialize Multimodal Embedding Model lazily
_multimodal_model = None

def _get_multimodal_model():
    global _multimodal_model
    if _multimodal_model is None:
        vertexai.init(project=PROJECT_ID, location=LOCATION)
        _multimodal_model = MultiModalEmbeddingModel.from_pretrained("multimodalembedding@001")
    return _multimodal_model


# In-Memory High-Speed Cache for Tool Latency Reduction
_ALARM_CACHE: Dict[str, str] = {}
_VISUAL_CACHE: Dict[str, str] = {}
_KNOWLEDGE_CACHE: Dict[str, str] = {}
_EMBEDDING_CACHE: Dict[str, List[float]] = {}


def _log_audit(event_type: str, details: Dict[str, Any], severity: str = "INFO"):
    """Emits structured audit log to Google Cloud Logging."""
    payload = {
        "timestamp": time.time(),
        "service": "carrier-chiller-agent",
        "event_type": event_type,
        **details
    }
    if _audit_logger:
        try:
            _audit_logger.log_struct(payload, severity=severity)
        except Exception as e:
            print(f"[Logging Warn] Failed to log struct: {e}")
    else:
        print(f"[AUDIT {severity}] {json.dumps(payload)}")


def carrier_knowledge_search(query: str, model_series: str = "", top_k: int = 5) -> str:
    """Performs unified hybrid search (dense semantic + BM25 lexical with dynamic RRF ranking) across Carrier manuals.
    Handles general engineering questions, troubleshooting, maintenance steps, AND exact fault/alarm codes (e.g. T051, A036, 014, P101).

    Args:
        query: Technical question, fault/alarm code, maintenance procedure, wiring check, or specification.
        model_series: Optional model filter ('19XR', '23XRV', '30HX', '30RC', '30XV'). Always specify if equipment is known.
        top_k: Number of relevant sections to retrieve (default: 5).

    Returns:
        Formatted technical excerpts with exact citations (manual form number, section, page number).
    """
    start_time = time.time()
    model_series = model_series.strip().upper() if model_series else ""
    filt = _make_field_filter("model_series", model_series)

    # Detect if query specifies an alarm code (e.g. 'T051', 'A036', '014', 'P101')
    alarm_tokens = re.findall(r'\b([A-Z]?\d{2,4}[A-Z]?)\b', query.upper())
    known_models = {"19XR", "23XRV", "30HX", "30RC", "30XV", "06N", "06NA", "06NW"}
    valid_alarms = [c for c in alarm_tokens if c not in known_models and not (len(c) == 4 and c.startswith("20"))]
    detected_alarm = valid_alarms[0] if valid_alarms else None

    # 1. Fast-path In-Memory Alarm Cache (<1ms)
    if detected_alarm and model_series:
        alarm_cache_key = f"{model_series}:{detected_alarm}"
        if alarm_cache_key in _ALARM_CACHE:
            latency_ms = (time.time() - start_time) * 1000
            _log_audit("TOOL_INVOCATION_CACHE_HIT", {
                "tool": "carrier_knowledge_search",
                "cache_type": "alarm_fast_path",
                "cache_key": alarm_cache_key,
                "latency_ms": round(latency_ms, 2)
            })
            return _ALARM_CACHE[alarm_cache_key]

    # 2. General Knowledge Cache Check
    clean_query = query.strip().lower()
    cache_key = f"{model_series}:{clean_query}:{top_k}"
    if cache_key in _KNOWLEDGE_CACHE:
        latency_ms = (time.time() - start_time) * 1000
        _log_audit("TOOL_INVOCATION_CACHE_HIT", {
            "tool": "carrier_knowledge_search",
            "cache_type": "knowledge_cache",
            "cache_key": cache_key,
            "latency_ms": round(latency_ms, 2)
        })
        return _KNOWLEDGE_CACHE[cache_key]

    _log_audit("TOOL_INVOCATION_START", {
        "tool": "carrier_knowledge_search",
        "query": query,
        "model_series": model_series,
        "detected_alarm": detected_alarm,
        "top_k": top_k
    })

    try:
        # Dynamically bias RRF weights: if an alarm code is present, boost BM25 lexical weight
        rrf_weights = [0.8, 2.0] if detected_alarm else [1.0, 1.0]

        searches = [
            vectorsearch_v1beta.Search(
                semantic_search=vectorsearch_v1beta.SemanticSearch(
                    search_text=query,
                    search_field="text_embedding",
                    task_type="QUESTION_ANSWERING",
                    filter=filt,
                    top_k=top_k,
                    output_fields=vectorsearch_v1beta.OutputFields(
                        data_fields=["chunk_id", "model_series", "form_number", "page_number", "section", "content", "has_image", "image_url"]
                    ),
                )
            ),
            vectorsearch_v1beta.Search(
                text_search=vectorsearch_v1beta.TextSearch(
                    search_text=detected_alarm or query,
                    data_field_names=["content"],
                    filter=filt,
                    top_k=top_k,
                    output_fields=vectorsearch_v1beta.OutputFields(
                        data_fields=["chunk_id", "model_series", "form_number", "page_number", "section", "content", "has_image", "image_url"]
                    ),
                )
            ),
        ]

        hybrid_req = vectorsearch_v1beta.BatchSearchDataObjectsRequest(
            parent=COLLECTION_NAME,
            searches=searches,
            combine=vectorsearch_v1beta.BatchSearchDataObjectsRequest.CombineResultsOptions(
                ranker=vectorsearch_v1beta.Ranker(
                    rrf=vectorsearch_v1beta.ReciprocalRankFusion(weights=rrf_weights)
                )
            )
        )

        response = _search_client.batch_search_data_objects(request=hybrid_req)
        latency_ms = (time.time() - start_time) * 1000

        results = []
        citations = []
        if response.results and response.results[0].results:
            for item in response.results[0].results:
                data = dict(item.data_object.data)
                chunk_id = data.get("chunk_id", "")
                m_series = data.get("model_series", "")
                form = data.get("form_number", "")
                page = data.get("page_number", "")
                section = data.get("section", "")
                content = data.get("content", "")
                has_image = data.get("has_image", False)
                image_url = data.get("image_url", "")

                citation_str = f"[Carrier Form {form}, Page {int(page) if isinstance(page, (int, float)) else page}, Section: {section}]"
                citations.append({"chunk_id": chunk_id, "form": form, "page": page, "section": section})

                formatted_chunk = f"--- Source Citation: {citation_str} (Equipment: Carrier {m_series}) ---\n{content}\n"
                if has_image and image_url:
                    formatted_chunk += f"Associated Schematic Diagram: {image_url}\n"
                results.append(formatted_chunk)

        _log_audit("TOOL_INVOCATION_SUCCESS", {
            "tool": "carrier_knowledge_search",
            "latency_ms": latency_ms,
            "results_found": len(results),
            "citations": citations,
            "rrf_weights": rrf_weights
        })

        if not results:
            if detected_alarm:
                return f"Alarm code '{detected_alarm}' not found in Carrier {model_series or 'documentation'}. Please verify the code or check if it applies to another model."
            return f"No documentation found in Carrier knowledge base for query: '{query}' (Filter: {model_series or 'None'})."

        output_str = "\n\n".join(results)
        _KNOWLEDGE_CACHE[cache_key] = output_str
        if detected_alarm and model_series:
            _ALARM_CACHE[f"{model_series}:{detected_alarm}"] = output_str

        return output_str

    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        _log_audit("TOOL_INVOCATION_ERROR", {
            "tool": "carrier_knowledge_search",
            "latency_ms": latency_ms,
            "error": str(e)
        }, severity="ERROR")
        return f"Error executing knowledge search: {e}"


def carrier_visual_search(query_description: str, model_series: str = "", top_k: int = 3) -> str:
    """Finds exact Carrier electrical schematics, piping diagrams, and control panel layouts by description.

    Args:
        query_description: Visual description of the schematic (e.g. 'CIOB J40 wiring diagram', 'compressor starter schematic', 'refrigerant piping').
        model_series: Optional model filter ('19XR', '23XRV', '30HX', '30RC', '30XV').
        top_k: Number of diagrams to return (default: 3).

    Returns:
        Markdown list of diagrams with high-resolution image URLs, page numbers, and manual references.
    """
    start_time = time.time()
    model_series = model_series.strip().upper() if model_series else ""
    filt = _make_field_filter("model_series", model_series)

    clean_desc = query_description.strip().lower()
    clean_series = model_series or "ALL"
    cache_key = f"{clean_series}:{clean_desc}:{top_k}"


    # Check In-Memory Visual Cache
    if cache_key in _VISUAL_CACHE:
        latency_ms = (time.time() - start_time) * 1000
        _log_audit("TOOL_INVOCATION_CACHE_HIT", {
            "tool": "carrier_visual_search",
            "cache_key": cache_key,
            "latency_ms": round(latency_ms, 2)
        })
        return _VISUAL_CACHE[cache_key]

    _log_audit("TOOL_INVOCATION_START", {
        "tool": "carrier_visual_search",
        "query_description": query_description,
        "model_series": model_series,
        "top_k": top_k
    })

    try:
        # Check text embedding cache for multimodal search
        if clean_desc in _EMBEDDING_CACHE:
            query_vector = _EMBEDDING_CACHE[clean_desc]
        else:
            model = _get_multimodal_model()
            v_emb = model.get_embeddings(contextual_text=f"Carrier Chiller schematic: {query_description}")
            query_vector = list(v_emb.text_embedding)
            _EMBEDDING_CACHE[clean_desc] = query_vector

        req = vectorsearch_v1beta.SearchDataObjectsRequest(
            parent=COLLECTION_NAME,
            vector_search=vectorsearch_v1beta.VectorSearch(
                search_field="visual_embedding",
                vector={"values": query_vector},
                filter=filt,
                top_k=top_k,
                output_fields=vectorsearch_v1beta.OutputFields(
                    data_fields=["chunk_id", "model_series", "form_number", "page_number", "diagram_caption", "image_url", "content"]
                )
            )
        )

        response = list(_search_client.search_data_objects(req))
        latency_ms = (time.time() - start_time) * 1000

        results = []
        diagrams = []
        for r in response:
            d = dict(r.data_object.data)
            cid = d.get("chunk_id", "")
            form = d.get("form_number", "")
            page = d.get("page_number", "")
            caption = d.get("diagram_caption", "Schematic Diagram")
            img_url = d.get("image_url", "")
            m_series = d.get("model_series", "")

            diagrams.append({"chunk_id": cid, "caption": caption, "url": img_url})
            entry = (
                f"### {caption}\n\n"
                f"![{caption}]({img_url})\n\n"
                f"- **Model**: Carrier {m_series}\n"
                f"- **Reference**: Form {form}, Page {int(page) if isinstance(page, (int, float)) else page}\n"
            )
            results.append(entry)

        _log_audit("TOOL_INVOCATION_SUCCESS", {
            "tool": "carrier_visual_search",
            "latency_ms": latency_ms,
            "results_found": len(results),
            "diagrams": diagrams
        })

        if not results:
            return f"No visual schematics found for '{query_description}' (Model: {model_series or 'Any'})."

        output_str = "\n\n".join(results)
        _VISUAL_CACHE[cache_key] = output_str
        return output_str

    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        _log_audit("TOOL_INVOCATION_ERROR", {
            "tool": "carrier_visual_search",
            "latency_ms": latency_ms,
            "error": str(e)
        }, severity="ERROR")
        return f"Error executing visual search: {e}"


def carrier_alarm_lookup(alarm_code: str, model_series: str) -> str:
    """Legacy alias: delegates directly to unified carrier_knowledge_search.

    Args:
        alarm_code: Exact alarm code (e.g., 'T051', 'A036', '014', 'P101', 'T055').
        model_series: Chiller model series ('19XR', '23XRV', '30HX', '30RC', '30XV').

    Returns:
        Direct diagnostic resolution, cause analysis, and field service instructions.
    """
    return carrier_knowledge_search(query=alarm_code, model_series=model_series, top_k=3)

