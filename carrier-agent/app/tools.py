"""
Carrier Chiller Engineering Agent Tools.
Provides Agent Retrieval tools powered by Google Cloud Vector Search 2.0:
- carrier_knowledge_search (Hybrid search + RRF)
- carrier_visual_search (Multimodal visual vector search)
- carrier_alarm_lookup (Targeted diagnostic alarm resolution)

All tools emit structured JSON audit telemetry to Google Cloud Logging.
"""

import os
import time
import json
from typing import Optional, List, Dict, Any

from google.cloud import vectorsearch_v1beta
from google.cloud import logging as cloud_logging
import vertexai
from vertexai.vision_models import MultiModalEmbeddingModel, Image as VertexImage

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "genai-demos-391416")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
COLLECTION_NAME = f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/carrier-chiller-docs"

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
    """Performs hybrid search (semantic + full-text with RRF ranking) across Carrier engineering manuals.

    Args:
        query: Technical question, maintenance procedure, wiring check, or specification.
        model_series: Optional model filter ('19XR', '23XRV', '30HX', '30RC', '30XV'). Always specify if the user mentions equipment.
        top_k: Number of relevant sections to retrieve (default: 5).

    Returns:
        Formatted technical excerpts with exact citations (manual form number, section, page number).
    """
    start_time = time.time()
    model_series = model_series.strip().upper() if model_series else ""
    filt = {"model_series": {"$eq": model_series}} if model_series else None

    # Check In-Memory Cache
    clean_query = query.strip().lower()
    cache_key = f"{model_series}:{clean_query}:{top_k}"
    if cache_key in _KNOWLEDGE_CACHE:
        latency_ms = (time.time() - start_time) * 1000
        _log_audit("TOOL_INVOCATION_CACHE_HIT", {
            "tool": "carrier_knowledge_search",
            "cache_key": cache_key,
            "latency_ms": round(latency_ms, 2)
        })
        return _KNOWLEDGE_CACHE[cache_key]

    _log_audit("TOOL_INVOCATION_START", {
        "tool": "carrier_knowledge_search",
        "query": query,
        "model_series": model_series,
        "top_k": top_k
    })

    try:
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
                    search_text=query,
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
                    rrf=vectorsearch_v1beta.ReciprocalRankFusion(weights=[1.0, 1.0])
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
            "citations": citations
        })

        if not results:
            return f"No documentation found in Carrier knowledge base for query: '{query}' (Filter: {model_series or 'None'})."

        output_str = "\n\n".join(results)
        _KNOWLEDGE_CACHE[cache_key] = output_str
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
    filt = {"model_series": {"$eq": model_series}} if model_series else None

    # Check In-Memory Visual Cache
    clean_desc = query_description.strip().lower()
    clean_series = model_series or "ALL"
    cache_key = f"{clean_series}:{clean_desc}:{top_k}"
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
            entry = f"### {caption}\n- **Model**: Carrier {m_series}\n- **Reference**: Form {form}, Page {int(page) if isinstance(page, (int, float)) else page}\n- **Image URL**: {img_url}\n"
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
    """Specialized lookup for Carrier chiller alarm codes, trip conditions, and troubleshooting steps.

    Args:
        alarm_code: Exact alarm code (e.g., 'T051', 'A036', '014', 'P101', 'T055').
        model_series: Chiller model series ('19XR', '23XRV', '30HX', '30RC', '30XV'). Required to prevent cross-manual diagnostics.

    Returns:
        Direct diagnostic resolution, cause analysis, and field service instructions.
    """
    start_time = time.time()
    clean_code = alarm_code.strip().upper()
    model_series = model_series.strip().upper()

    # Check In-Memory Alarm Cache
    cache_key = f"{model_series}:{clean_code}"
    if cache_key in _ALARM_CACHE:
        latency_ms = (time.time() - start_time) * 1000
        _log_audit("TOOL_INVOCATION_CACHE_HIT", {
            "tool": "carrier_alarm_lookup",
            "cache_key": cache_key,
            "latency_ms": round(latency_ms, 2)
        })
        return _ALARM_CACHE[cache_key]

    _log_audit("TOOL_INVOCATION_START", {
        "tool": "carrier_alarm_lookup",
        "alarm_code": clean_code,
        "model_series": model_series
    })

    try:
        filt = {"model_series": {"$eq": model_series}}
        req = vectorsearch_v1beta.SearchDataObjectsRequest(
            parent=COLLECTION_NAME,
            text_search=vectorsearch_v1beta.TextSearch(
                search_text=clean_code,
                data_field_names=["content"],
                filter=filt,
                top_k=3,
                output_fields=vectorsearch_v1beta.OutputFields(
                    data_fields=["chunk_id", "model_series", "form_number", "page_number", "section", "content"]
                )
            )
        )

        response = list(_search_client.search_data_objects(req))
        latency_ms = (time.time() - start_time) * 1000

        findings = []
        for r in response:
            d = dict(r.data_object.data)
            form = d.get("form_number", "")
            page = d.get("page_number", "")
            section = d.get("section", "")
            content = d.get("content", "")
            findings.append(f"Source [Form {form}, Page {int(page) if isinstance(page, (int, float)) else page}, Section: {section}]:\n{content}")

        _log_audit("TOOL_INVOCATION_SUCCESS", {
            "tool": "carrier_alarm_lookup",
            "alarm_code": clean_code,
            "latency_ms": latency_ms,
            "matches_found": len(findings)
        })

        if not findings:
            return f"Alarm code '{clean_code}' not found in Carrier {model_series} documentation. Please verify the code or check if it applies to another model."

        output_str = "\n\n".join(findings)
        _ALARM_CACHE[cache_key] = output_str
        return output_str

    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        _log_audit("TOOL_INVOCATION_ERROR", {
            "tool": "carrier_alarm_lookup",
            "latency_ms": latency_ms,
            "error": str(e)
        }, severity="ERROR")
        return f"Error performing alarm lookup: {e}"
