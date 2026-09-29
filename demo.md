# Google Cloud Demo Script: Carrier Chiller Multimodal AI Assistant
## End-to-End Walkthrough: Vector Search 2.0 (Agent Retrieval), Google ADK 2.0, Agent Platform Runtime & Enterprise Observability

---

## 1. Demo Overview & Metadata

| Metadata Field | Value |
| :--- | :--- |
| **Solution Name** | Carrier Industrial Chiller Multimodal Field Specialist AI |
| **Target Audience** | Enterprise Technical Decision Makers, HVAC Field Directors, Cloud Architects, Customer Engineers |
| **Demo Duration** | 12 – 15 Minutes |
| **Primary GCP Products** | **Vector Search 2.0** (Agent Retrieval), **Agent Platform Runtime**, **Agent Registry**, **Google ADK 2.0**, **Gemini 2.5 Flash**, **Vertex AI Multimodal Embeddings**, **Google Cloud Storage**, **Google Cloud Logging** |
| **GCP Project ID** | `genai-demos-391416` (Project Number: `101296135052`) |
| **GCP Region** | `us-central1` |
| **Live Web App URL** | [http://localhost:3000](http://localhost:3000) |
| **Backend API URL** | [http://localhost:8000](http://localhost:8000) |

---

## 2. Pre-Flight Checklist (Setup in 2 Minutes)

Before opening your screen share, verify that both the backend and frontend are live:

1. **Verify Services in Terminal**:
   ```bash
   # Check Backend Health (FastAPI + Agent Runtime)
   curl -s http://localhost:8000/api/health
   # Expected: {"status":"healthy","project_id":"genai-demos-391416", ...}
   ```
2. **Open Browser Tabs**:
   * **Tab 1 (Live Demo Surface)**: [http://localhost:3000](http://localhost:3000)
   * **Tab 2 (Google Cloud Console - Vector Search 2.0)**:
     `https://console.cloud.google.com/vertex-ai/vector-search?project=genai-demos-391416`
   * **Tab 3 (Google Cloud Console - Agent Platform / Reasoning Engines)**:
     `https://console.cloud.google.com/vertex-ai/reasoning-engines?project=genai-demos-391416`
   * **Tab 4 (Google Cloud Console - Cloud Storage Assets)**:
     `https://console.cloud.google.com/storage/browser/genai-demos-391416-carrier-assets?project=genai-demos-391416`
   * **Tab 5 (Google Cloud Console - Cloud Logging)**:
     `https://console.cloud.google.com/logs/query?project=genai-demos-391416`

---

## 3. Demo Flow & Stage-by-Stage Script

```
┌────────────────────────────────────────────────────────────────────────┐
│                          DEMO RUN-OF-SHOW                              │
│                                                                        │
│  [00:00 - 02:00] Stage 1: The Business Problem & Architectural Vision  │
│  [02:00 - 05:00] Stage 2: GCP Console Tour (The Enterprise Foundation) │
│  [05:00 - 11:00] Stage 3: Live Interactive Demo (Technician Web App)   │
│  [11:00 - 13:00] Stage 4: Under-the-Hood Telemetry (Cloud Logging)     │
│  [13:00 - 15:00] Stage 5: Summary, Enterprise Value & Q&A             │
└────────────────────────────────────────────────────────────────────────┘
```

---

### Stage 1: The Business Problem & Architectural Vision (2 Minutes)

#### 🎙️ What to Say (Opening Pitch):
> *"When a commercial chiller goes down in a hospital, semiconductor fab, or Tier-IV data center, the financial loss easily exceeds \$10,000 to \$50,000 every single hour. 
> 
> Today, field service technicians face a massive challenge: Carrier manufactures multiple distinct chiller lines—such as centrifugal 19XR, screw 23XRV, and air-cooled 30HX, 30RC, and 30XV machines. Across just these five models, technicians must navigate over 850 pages of dense technical manuals containing intricate electrical wiring schematics, proprietary bus protocols (CCN vs. BACnet), and high-voltage safety interlocks.
>
> Generic LLM chatbots fail here because they hallucinate pinouts, cross-contaminate procedures between incompatible chiller lines, and cannot display exact visual wiring diagrams.
>
> Today, I'm going to demonstrate an enterprise-grade solution built natively on Google Cloud: **Vector Search 2.0 (Agent Retrieval)**, **Google Agent Development Kit (ADK 2.0)**, and **Agent Platform Runtime**. We have ingested 858 pages of Carrier manuals into a unified hybrid and multimodal vector index, delivering sub-second grounded diagnostics, live inline schematics, and complete audit logging."*

---

### Stage 2: Google Cloud Console Tour (3 Minutes)

Switch to your browser and walk through the GCP infrastructure tabs.

#### 1. Agent Retrieval in Vector Search 2.0 (Tab 2)
* **What to Show**:
  * Point out collection: `carrier-chiller-docs` under `projects/genai-demos-391416/locations/us-central1`.
  * Highlight the **1,084 data objects** parsed and indexed from all 5 Carrier service manuals.
* **Key Talking Points**:
  * **Instant kNN**: Explain that unlike previous generations of vector search that required long index build cycles, **Vector Search 2.0** offers instant kNN—documents and schematics are searchable immediately upon ingestion with zero downtime.
  * **Dual Vector Schema**: Point out that the collection stores **two distinct vector fields in a single collection**:
    1. `text_embedding` (768-dim `gemini-embedding-001` auto-generated server-side).
    2. `visual_embedding` (1408-dim `multimodalembedding@001` for schematic diagram retrieval).
  * **Hybrid Search + Reciprocal Rank Fusion (RRF)**: Explain that Vector Search 2.0 automatically executes dense semantic search and BM25 lexical keyword search simultaneously, blending scores using RRF `[1.0, 1.0]` to guarantee both semantic intent and exact alarm codes (like `T051` or `A036`) are retrieved without keyword miss.
  * **Metadata Isolation**: Emphasize the `model_series` filter. When a technician is working on a `30HX`, the search engine strictly filters by `model_series == "30HX"`, preventing catastrophic cross-manual pinout hallucinations.

#### 2. Agent Platform Runtime & Agent Registry (Tab 3)
* **What to Show**:
  * Navigate to Vertex AI Reasoning Engines / Agent Platform.
  * Point out the deployed agent instance:
    `projects/101296135052/locations/us-central1/reasoningEngines/5108959393542569984`
* **Key Talking Points**:
  * **Google ADK 2.0**: Built using Google's official Agent Development Kit (`google-adk`), providing enterprise session memory, typed tool routing, and automated retry handling.
  * **Agent Platform Runtime**: Fully managed serverless deployment target (`agent_runtime`) enabling autoscaling, secure credential binding, and stateful multi-turn conversation memory.
  * **Agent Registry**: Governed under the central Gemini Enterprise Agent Registry, providing corporate cataloging, versioning, and compliance gating.

#### 3. Visual Asset Store & CDN Simulation (Tab 4)
* **What to Show**:
  * Open Cloud Storage bucket `gs://genai-demos-391416-carrier-assets/`.
  * Show the 154 high-resolution `.webp` diagram files extracted from the manuals.
* **Key Talking Points**:
  * Point out that each schematic is pre-compressed to modern WebP format and configured with `Cache-Control: public, max-age=86400`, simulating high-speed Cloud CDN delivery directly from GCS.

---

### Stage 3: Live Interactive Demo on Field Technician Web App (6 Minutes)

Switch to **Tab 1** ([http://localhost:3000](http://localhost:3000)).

```text
┌────────────────────────────────────────────────────────────────────────┐
│  Carrier Chiller Field Specialist (Gemini 2.5 Flash)                   │
│  [19XR]  [23XRV]  [30HX ●]  [30RC]  [30XV]  [All Models]  [New Chat]   │
├────────────────────────────────────────────────────────────────────────┤
│  ⚡ Sub-2s Turnaround  |  🔍 Vector Search 2.0  |  📡 ADK Runtime      │
└────────────────────────────────────────────────────────────────────────┘
```

#### Demo Scenario 1: Targeted Alarm Diagnostics (Model: 30HX)
1. **Action**: Click the **`30HX`** model pill at the top of the chat window.
2. **Type or Paste Prompt**:
   ```text
   What does alarm T051 mean on 30HX?
   ```
3. **What to Point Out Live on Screen**:
   * **Instant Token Streaming (TTFT < 1.5s)**: Point out how the text begins streaming across the screen almost immediately, eliminating perceived delay.
   * **Live Tool Execution Badge**: Show the pill indicator displaying `carrier_knowledge_search`. The agent dynamically unified dense semantic retrieval and BM25 lexical search with RRF to resolve the exact alarm code and related troubleshooting procedures.
   * **Grounded Diagnostic Precision**: The agent identifies `T051` as a **Compressor A1 Failure Alert** sent from the Compressor Protection Module (CPM) to the Main Base Board (MBB).
   * **Actionable Field Instructions**: It tells the technician the exact secret diagnostic button combination: press **`ENTER` and `ESCAPE` simultaneously** on the Navigator display to view the underlying trip reason.
   * **Strict Citations**: Point out the primary source citation:
     `[Carrier Form 30HX-2T, Page 42, Section: TROUBLESHOOTING]`.
   * **Real-Time Latency Badge**: Highlight the bottom badge showing exact turnaround time (~3.8s total, ~1.4s TTFT).

---

#### Demo Scenario 2: Conversational Multi-Turn Memory & Sub-Millisecond Cache Hit
1. **Action**: Without selecting any buttons or mentioning the model, type:
   ```text
   What are the possible fault conditions that lead to this alarm?
   ```
2. **What to Point Out Live on Screen**:
   * **Context Awareness**: The technician didn't repeat "30HX" or "T051". The ADK 2.0 `InMemorySessionService` maintained the conversation thread.
   * **In-Memory Cache Hit (< 1 ms)**: Point out the speed! Because the alarm lookup was already loaded in memory, the tool step took **< 1 millisecond**, and the entire answer completed in **~2.4 seconds**.
   * **Comprehensive Fault Analysis**: The response categorizes the exact faults directly from Form 30HX-2T:
     * *High Pressure Switch Trip*
     * *No Motor Current / Contactor Failure*
     * *Current Phase Reversal / Phase Loss*
     * *Ground Fault Trip*

---

#### Demo Scenario 3: Proactive First-Turn Schematic & Pinout Retrieval (Model: 30XV)
1. **Action**: Click the **`30XV`** model pill (this switches models and starts a clean session).
2. **Type or Paste Prompt**:
   ```text
   What is the exact terminal pinout for the Dual Emergency Stop option on the Carrier 30XV chiller?
   ```
3. **What to Point Out Live on Screen**:
   * **Proactive Multimodal Retrieval**: Emphasize that the user asked for a *terminal pinout* without explicitly saying "show me a diagram". The agent **proactively invoked `carrier_visual_search` in the very first turn** rather than making the technician ask twice or telling them to "refer to the manual".
   * **Exact Pinout Verification**: Pins 1 & 2 on the Centralized I/O Board (CIOB) J40 terminal correspond to the **Dual Emergency Stop switch** (normally closed).
   * **Inline High-Resolution Diagram**: The schematic diagrams (`Fig. 106 — 30XV Typical Field Wiring Schematic` and `Fig. 119 — 30XV 24V Control Wiring`) render **fully opened edge-to-edge right inside the conversation stream**.
   * **LOTO Safety Warnings**: Point out mandatory Lockout/Tagout and DC bus capacitor discharge checks.

---

#### Demo Scenario 4: Cross-Modal Visual Search (Photo / Description to Schematic)
1. **Action**: Click the **"Visual Search"** tab or modal button (or enter):
   ```text
   refrigerant piping schematic for 19XR
   ```
2. **What to Point Out Live on Screen**:
   * Explain that this uses the **`multimodalembedding@001`** 1408-dimensional vector space.
   * The system retrieves the exact piping diagram from Form 19XR-1T, Page 12, demonstrating cross-modal image retrieval without requiring keyword tags.

---

#### Demo Scenario 5: Safety Protocol & Mild Flammable Refrigerant (Model: 30RC)
1. **Action**: Click the **`30RC`** model pill.
2. **Type or Paste Prompt**:
   ```text
   What safety precautions are required before servicing the refrigeration circuit on 30RC?
   ```
3. **What to Point Out Live on Screen**:
   * **A2L Flammability Warning**: The agent immediately detects that the Carrier 30RC utilizes **R-32**, an A2L mildly flammable refrigerant.
   * It highlights mandatory continuous mechanical ventilation, certified spark-free recovery machines, and combustible gas leak detectors before initiating brazing or charging.
   * Citations: `[Carrier Form 30RC-1T, Page 6, Section: SAFETY CONSIDERATIONS]`.

---

#### Demo Scenario 6: Negative Testing & Competitor Guardrails
1. **Action**: In the chat box, ask about a competitor's equipment:
   ```text
   How do I clear an oil pressure trip on a Trane CenTraVac CVHE chiller?
   ```
2. **What to Point Out Live on Screen**:
   * **Zero Hallucination Guardrail**: The agent politely declines, stating:
     *"I am certified exclusively for Carrier commercial chillers (19XR, 23XRV, 30HX, 30RC, and 30XV). I cannot diagnose or provide service procedures for Trane equipment."*
   * Explain to the audience why this is critical in enterprise HVAC: **applying Trane CenTraVac oil pressure procedures to a Carrier chiller could destroy a \$200,000 centrifugal compressor**.

---

### Stage 4: Under-the-Hood Telemetry in Google Cloud Logging (2 Minutes)

Switch to **Tab 5** (Google Cloud Logging Logs Explorer).

1. **Run the Query**:
   ```sql
   resource.type="global"
   logName=~"projects/genai-demos-391416/logs/carrier-(agent-audit|api-server)"
   ```
2. **Expand the Most Recent Log Entry**:
   * Point out the structured JSON payload:
     ```json
     {
       "service": "carrier-chiller-agent",
       "event_type": "TOOL_INVOCATION_CACHE_HIT",
       "tool": "carrier_knowledge_search",
       "cache_key": "30HX:T051",
       "latency_ms": 0.08,
       "timestamp": 1727214732.1
     }
     ```
   * Show the corresponding API server log:
     ```json
     {
       "service": "carrier-api-server",
       "event": "CHAT_STREAM_COMPLETED",
       "session_id": "sess_89f0a21bc901",
       "model_series": "30HX",
       "server_latency_ms": 2423.7,
       "tools_count": 1,
       "tools_list": ["carrier_knowledge_search"]
     }
     ```
3. **Key Talking Points**:
   * **Enterprise Compliance & Auditability**: Every single prompt, tool execution, cache hit, and latency metric is audited to Cloud Logging.
   * **BigQuery Integration**: These logs stream directly into BigQuery for automated fleet reporting, SLA auditing, and tracking technician diagnostic speed.

---

### Stage 5: Summary & ROI Value Wrap-Up (2 Minutes)

#### 🎙️ What to Say (Closing):
> *"To summarize what we've seen today:
>
> 1. **Vector Search 2.0 (Agent Retrieval)** eliminated the traditional barrier to vector search: zero index deployment delay, hybrid dense+lexical search with RRF ranking, and dual text+visual schemas in a single collection.
> 2. **Google ADK 2.0 & Agent Platform Runtime** provided enterprise-grade agent orchestration, tool routing, and multi-turn conversational memory running fully managed on serverless Google infrastructure.
> 3. **Sub-2s Perceived Latency**: With Server-Sent Events (SSE) streaming and in-memory LRU tool caching, time-to-first-token dropped from 12 seconds down to 1.4 seconds.
> 4. **Multimodal Visual Intelligence**: Technicians receive exact, high-resolution wiring schematics inline on their mobile screens, cite exact manual pages, and avoid dangerous cross-model hallucinations.
>
> This architecture directly translates to reduced downtime, safer job sites, and significant operational cost savings across commercial HVAC service fleets."*

---

## 4. Presenter Cheat Sheet & Fallback Reference

### Quick Copy-Paste Demo Prompts

| # | Demo Case | Model Pill | Exact Prompt String to Copy | Expected Result |
| :- | :--- | :--- | :--- | :--- |
| **1** | **Alarm T051** | `30HX` | `What does alarm T051 mean on 30HX?` | Compressor A1 Failure, Navigator ENTER+ESCAPE instructions, Form 30HX-2T citation. |
| **2** | **Multi-Turn Faults** | *(Same)* | `What are the possible fault conditions that lead to this alarm?` | Cache hit (<1ms tool latency), bulleted list of 8 electrical/mechanical faults. |
| **3** | **Proactive Schematic** | `30XV` | `What is the exact terminal pinout for the Dual Emergency Stop option on the Carrier 30XV chiller?` | Proactively fetches wiring schematics in turn 1 without asking twice, CIOB J40 pins 1 & 2, LOTO safety warning. |
| **4** | **Safety Protocols** | `30RC` | `What safety precautions are required before servicing the refrigeration circuit on 30RC?` | R-32 A2L mild flammability protocol, ventilation, leak detection, Form 30RC-1T. |
| **5** | **Competitor Guardrail**| `All` | `How do I clear an oil pressure trip on a Trane CenTraVac CVHE chiller?` | Polite decline: exclusively certified for Carrier equipment. |

### Technical Architecture Quick Reference Table

| Layer | Component | GCP Resource / Detail |
| :--- | :--- | :--- |
| **Frontend** | React 19 + TypeScript + Vite | Port 3000 (`http://localhost:3000`) |
| **Backend** | FastAPI + StreamingResponse (SSE) | Port 8000 (`http://localhost:8000`) |
| **Agent Core** | Google ADK 2.0 (`google-adk`) | `carrier-agent/app/agent.py` |
| **Runtime Target**| Agent Platform Runtime | Reasoning Engine: `5108959393542569984` |
| **Vector Engine** | Vector Search 2.0 | `carrier-chiller-docs` (Instant kNN, Hybrid RRF) |
| **Embeddings** | Dual Vector Schema | `gemini-embedding-001` (768) + `multimodalembedding@001` (1408) |
| **Image CDN** | Cloud Storage + Proxy | `gs://genai-demos-391416-carrier-assets` |
| **Observability** | Cloud Logging | Loggers: `carrier-agent-audit`, `carrier-api-server` |
