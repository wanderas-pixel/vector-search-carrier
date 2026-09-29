# Carrier Specialist AI: Multimodal Field Engineering Assistant
### Enterprise Agent Retrieval (Vector Search 2.0), Google ADK 2.0, and Vertex AI Gemini 2.5 Flash

[![Google Cloud](https://img.shields.io/badge/Google_Cloud-Vector_Search_2.0-4285F4?logo=google-cloud&logoColor=white)](https://cloud.google.com/vertex-ai)
[![Agent Framework](https://img.shields.io/badge/Agent_Framework-Google_ADK_2.0-34A853?logo=google&logoColor=white)](https://cloud.google.com/products/gemini/enterprise)
[![Reasoning Engine](https://img.shields.io/badge/Reasoning_Model-Gemini_2.5_Flash-EA4335?logo=google-gemini&logoColor=white)](https://cloud.google.com/vertex-ai/generative-ai/docs/multimodal-overview)
[![Frontend](https://img.shields.io/badge/Frontend-React_19_+_TypeScript_+_Vite-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

---

## 1. Executive Summary & Vision

When a mission-critical commercial chiller plant experiences a fault in a hospital, semiconductor manufacturing cleanroom, or Tier-IV data center, downtime costs routinely surpass **\$10,000 to \$50,000 per hour**. 

Field service technicians face a formidable operational challenge: Carrier manufactures multiple distinct commercial chiller lines—including centrifugal (`19XR`), screw (`23XRV`), and air-cooled scroll/screw machines (`30HX`, `30RC`, `30XV`). Navigating across **858 pages of dense engineering manuals**, tracing high-voltage control board schematics, deciphering alphanumeric fault codes, and preventing cross-equipment pinout contamination requires extreme precision.

This project implements an enterprise-grade **Multimodal Field Specialist AI Assistant** built natively on **Google Cloud's next-generation Agentic Stack**:
* **Vertex AI Gemini 2.5 Flash Ingestion**: Native multimodal PDF comprehension extracts structured Markdown diagnostic tables, electrical schematics, and connector pinouts with sub-second processing speed and high cost efficiency (\$0.30 per 1,000 pages).
* **Vertex AI Vector Search 2.0 (Agent Retrieval)**: Real-time hybrid search engine with instant kNN, zero index deployment delay, and dual-vector schemas combining dense semantic vectors with lexical BM25 keyword matching via Reciprocal Rank Fusion (RRF).
* **Dual-Modal Embeddings**: Server-side auto-embeddings via `gemini-embedding-001` (768-dim) for text knowledge chunks alongside client-side `multimodalembedding@001` (1,408-dim) for high-resolution 300 DPI electrical schematics.
* **Google Agent Development Kit (ADK 2.0)**: Production-grade agent orchestration framework managing tool dispatching, conversational memory, and diagnostic workflows. Configured with `BuiltInPlanner(thinking_budget=0)` for ultra-low latency execution (<7s total turn) and instant first-token streaming.
* **Fleet-Wide Coverage**: Ingests, indexes, and isolates data across all 5 primary Carrier chiller series (`19XR`, `23XRV`, `30HX`, `30RC`, `30XV`).
* **Interactive React 19 Frontend**: Delivers natural language diagnostic chat, model filtering chips, instant quick scenario prompts, and inline edge-to-edge WebP schematic rendering.
* **End-to-End Enterprise Traceability**: Complete audit trails logged to Google Cloud Logging (`carrier-agent-audit`), stamping every response with deterministic chunk IDs and canonical citations: `[Carrier Form <form_number>, Page <page_number>, Section: <section_name>]`.

> For the comprehensive step-by-step technical architecture, schemas, and traceability contracts, see **[ARCHITECTURE.md](ARCHITECTURE.md)**.

---

## 2. High-Level Architecture

```
[ Carrier Manuals (858 Pages) ]
              │
              ▼
┌────────────────────────────────────────────────────────┐
│             CLOUD RUN INGESTION WORKER                 │
│         (Serverless Multi-Threaded Host)               │
│                                                        │
│  ├── 1. Gemini 2.5 Flash Vision: Tables & Schematics   │
│  ├── 2. Multimodal Embeddings: multimodalembedding@001 │
│  └── 3. Batch Ingestion: DataObject Batch Size = 50   │
└────────────────────────────────────────────────────────┘
              │
              ▼
┌────────────────────────────────────────────────────────┐
│             VERTEX AI VECTOR SEARCH 2.0                │
│             (carrier-chiller-docs)                     │
│                                                        │
│  ├── text_embedding: gemini-embedding-001 (768-dim)    │
│  ├── visual_embedding: multimodal (1408-dim)          │
│  └── Dynamic Reciprocal Rank Fusion (RRF) Hybrid Search│
└────────────────────────────────────────────────────────┘
              │
              ▼
┌────────────────────────────────────────────────────────┐
│               ONLINE RUNTIME & SERVING                 │
│                                                        │
│  ├── Google ADK 2.0 Agent (thinking_budget=0)          │
│  ├── Hybrid Retrieval & Schema Visual k-NN Tools      │
│  ├── FastAPI Streaming Backend (SSE, Port 8000)        │
│  └── React 19 Field Technician UI (Port 3000)          │
└────────────────────────────────────────────────────────┘
              │
              ▼
[ Google Cloud Logging: carrier-agent-audit Telemetry ]
```

---

## 3. Supported Chiller Fleet & Curated Quick Scenarios

The platform natively supports Carrier's five primary commercial chiller lines:

| Chiller Series | Compressor Type | Refrigerant | Manual Form | Curated Verification Scenario |
| :--- | :--- | :--- | :--- | :--- |
| **30HX** | Semi-Hermetic Screw | R-134a | `30HX-2T` | Main Base Board (MBB) Layout & J-Terminal Connectors (`Figure L`) |
| **30XV** | Variable-Speed Screw | R-134a | `30XV-6T` | Dual Emergency Stop Wiring Pinout (`CIOB J40 Pins 1-2`, `Fig. 106`) |
| **23XRV** | Tri-Rotor Screw / VFD | R-134a | `23XRV-3T` | VFD Control Wiring Schematic & Interface Terminals (`Fig. 7`) |
| **30RC** | Variable-Speed Scroll | R-32 (A2L) | `30RC-101T` | Field Wiring Schematic & A2L Low-GWP Refrigerant Safety Protocols (`Fig. 80`) |
| **19XR** | Hermetic Centrifugal | R-134a / R-513A | `19XR-2T` | Oil Differential Pressure Specs (6 psi startup) & Starter Wiring (`Page 50`) |

---

## 4. Key Architectural Highlights & Capabilities

### 1. Gemini 2.5 Flash Multimodal Extraction Engine
The ingestion pipeline leverages **Vertex AI Gemini 2.5 Flash** for direct, high-fidelity multimodal document understanding:
* **Direct Multimodal Processing**: Ingests high-resolution PDF pages natively without intermediate text rasterization steps.
* **Lossless Table Conversion**: Formats complex multi-column diagnostic charts, pressure-temperature ratings, and alarm matrices directly into GitHub-flavored Markdown.
* **Schematic & Pinout Extraction**: Identifies electrical boundary regions, isolates schematic figures, tags circuit components (`CIOB`, `MBB`, `TB1`), and extracts precise connector pinout mappings (e.g. `J40 Pins 1-2`).
* **High Efficiency**: Processes documentation catalogs at \$0.30 per 1,000 pages with full multimodal vision support.

### 2. Dual Embedding Strategy in Vector Search 2.0
* **`text_embedding` (768-dim)**: Automatically generated **server-side** by Vector Search 2.0 using `gemini-embedding-001` via structured templates (`Equipment: {model_series} | Manual: {form_number} | Page: {page_number}...`).
* **`visual_embedding` (1,408-dim)**: Generated **client-side in Cloud Run** via `multimodalembedding@001` by pairing 300 DPI WebP image bytes with extracted contextual domain text, allowing technicians to retrieve exact wiring diagrams via natural language.

### 3. High-Velocity Reasoning via BuiltInPlanner Configuration
To ensure field technicians receive instant guidance during critical plant servicing, the Google ADK 2.0 agent is tuned for immediate execution:
* **Sub-Second Vector Retrieval**: Vertex AI Vector Search 2.0 resolves complex hybrid k-NN queries in under 925 ms.
* **Targeted Reasoning Budget**: The ADK agent configures `BuiltInPlanner(thinking_budget=0)` to deliver immediate first-token streaming without unnecessary token generation overhead.
* **Rapid Turnaround**: Complete diagnostic turns—including hybrid retrieval, table formatting, and schematic linking—resolve in ~7 seconds.

---

## 5. Repository Structure

```
├── ARCHITECTURE.md              # Definitive end-to-end architecture & schemas
├── README.md                    # Solution overview and quickstart guide
├── backend/                     # FastAPI HTTP & Server-Sent Events (SSE) server
│   ├── server.py                # REST endpoints, image proxies, and streaming chat
│   └── requirements.txt
├── carrier-agent/               # Google Agent Development Kit (ADK) 2.0 core
│   ├── app/
│   │   ├── agent.py             # Agent definition & BuiltInPlanner configuration
│   │   └── tools.py             # Hybrid search & multimodal vector search tools
│   ├── tests/                   # Unit, integration, and evalset tests
│   └── README.md
├── frontend/                    # React 19 + TypeScript + Vite web portal
│   ├── src/
│   │   ├── App.tsx              # Chat interface, model selector, quick prompts
│   │   └── components/          # Message bubbles, diagram lightboxes, citations
│   └── package.json
├── ingestion/                   # Serverless ingestion engine (Cloud Run)
│   ├── gemini_flash_ingestion.py# Pure Gemini 2.5 Flash multimodal extraction engine
│   ├── cloud_run_worker.py      # Cloud Run multi-threaded batch ingestion worker
│   ├── Dockerfile               # Container build definition for Cloud Run Jobs
│   └── requirements.txt
└── setup_vector_search_2.py     # Vector Search 2.0 collection provisioning script
```

---

## 6. Quickstart Guide

### Prerequisites
* Google Cloud SDK (`gcloud`) authenticated via Application Default Credentials (ADC):
  ```bash
  gcloud auth application-default login
  gcloud config set project genai-demos-391416
  ```
* Python 3.11+
* Node.js 18+

### Step 1: Start the FastAPI Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```
Backend runs at `http://localhost:8000`.

### Step 2: Start the React Frontend
```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 3000
```
Frontend runs at `http://localhost:3000`.

### Step 3: (Optional) Re-Run Batch Ingestion via Cloud Run Worker
To re-process and index manuals using the multi-threaded worker:
```bash
cd ingestion
python cloud_run_worker.py --all --upload --concurrency 6
```

---

## 7. Telemetry & Governance

All tool executions, vector latencies, and citation lists are asynchronously exported to Google Cloud Logging under:
* **`carrier-agent-audit`**: Records user query, equipment model filter, RRF weights, Vector Search latency (ms), and retrieved manual citations.
* **`carrier-api-server`**: Records HTTP request life cycle, payload sizes, and SSE stream durations.

All access is secured via **Google Cloud IAM & Application Default Credentials (ADC)** with zero persistent API keys or secrets.
