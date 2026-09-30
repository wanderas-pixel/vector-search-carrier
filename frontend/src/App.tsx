import { useState, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ExternalLink,
  Image as ImageIcon,
  RefreshCw,
  Search,
  Send,
  Terminal,
  X,
  Zap,
} from "lucide-react";

interface ToolExecution {
  tool_name: string;
  args: Record<string, any>;
  latency_ms: number;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  modelSeries?: string;
  toolsUsed?: ToolExecution[];
  serverLatencyMs?: number;
  totalLatencyMs?: number; // Measured from enter key to DOM completion
  timestamp: string;
}

interface DiagramResult {
  chunk_id: string;
  model_series: string;
  form_number: string;
  page_number: number;
  caption: string;
  image_url: string;
  context_snippet: string;
}

interface AuditLogEntry {
  timestamp: string;
  severity: string;
  payload: Record<string, any>;
}

const CARRIER_MODELS = [
  { id: "All Models", label: "All Chiller Series", badge: "Universal" },
  { id: "19XR", label: "AquaEdge 19XR", badge: "Centrifugal" },
  { id: "23XRV", label: "AquaEdge 23XRV", badge: "Screw VFD" },
  { id: "30HX", label: "AquaForce 30HX", badge: "Water-Cooled" },
  { id: "30RC", label: "AquaForce 30RC", badge: "Scroll (R-32 A2L)" },
  { id: "30XV", label: "AquaForce 30XV", badge: "Variable Screw" },
];

function cleanMarkdown(t: string): string {
  if (!t) return "";
  // 1. Convert any text image links or bullet URLs to markdown image syntax
  // E.g. "- Image URL: http..." or "- **Image URL**: http..." -> "\n\n![Carrier Technical Schematic](http...)\n\n"
  let cleaned = t.replace(/(?:-\s*)?(?:\*\*)?Image URL(?:\*\*)?:\s*\[?(https?:\/\/[^\s\)]+(?:\/api\/image\/|\.webp|\.png|\.jpg|\.jpeg)[^\s\)]*)\]?/gi, "\n\n![Carrier Technical Schematic]($1)\n\n");
  // Also convert non-image markdown links pointing to diagrams: [Caption](http://.../api/image/...webp) -> ![Caption](http://.../api/image/...webp)
  cleaned = cleaned.replace(/(^|[^!])\[([^\]]+)\]\((https?:\/\/[^\s\)]+(?:\/api\/image\/|\.webp|\.png|\.jpg|\.jpeg)[^\s\)]*)\)/g, "$1\n\n![$2]($3)\n\n");
  // Also if an image URL is on a line by itself:
  cleaned = cleaned.replace(/(^|\n)(https?:\/\/[^\s\)]+\/api\/image\/[^\s\)]+\.(?:webp|png|jpg|jpeg))(\n|$)/gi, "$1\n![Carrier Technical Schematic]($2)\n$3");
  // 2. Separate merged table rows and delimiters (e.g. "| |:---" or "| | Alm-" or "| |"):
  cleaned = cleaned.replace(/\|\s*\|/g, "|\n|");
  // 3. Remove runaway ASCII divider lines (e.g. ------ without pipes)
  cleaned = cleaned.replace(/^[ \t]*[-=]{6,}[ \t]*$/gm, "");
  cleaned = cleaned.replace(/(?:^[ \t]*---[ \t]*$\n?){2,}/gm, "---\n");
  // 4. Remove any blank lines between table rows (tables require adjacent rows)
  cleaned = cleaned.replace(/\|\s*\n\s*\n\s*\|/g, "|\n|");
  cleaned = cleaned.replace(/\|\s*\n\s*\n\s*\|/g, "|\n|");
  // 5. Ensure citations that are glued together on one line are split cleanly onto their own lines
  cleaned = cleaned.replace(/(\[[^\]]+\])\s*(?=\[[^\]]+\])/g, "$1\n");
  // 6. Ensure blank line before citations at end of table
  cleaned = cleaned.replace(/(\|[^\n]+\|)\s*(\[[A-Z])/g, "$1\n\n$2");
  // 7. Ensure standalone images have blank lines around them
  cleaned = cleaned.replace(/([^\n])\n*(!\[[^\]]*\]\([^\)]+\))\n*([^\n])/g, "$1\n\n$2\n\n$3");
  cleaned = cleaned.replace(/\n{3,}/g, "\n\n");
  return cleaned;
}

const QUICK_PROMPTS = [
  {
    model: "30HX",
    title: "Main Base Board Layout",
    text: "Show me the Main Base Board (MBB) component layout and wiring connections for the 30HX chiller.",
  },
  {
    model: "30XV",
    title: "Dual Emergency Stop Pinout",
    text: "What is the exact terminal pinout for the Dual Emergency Stop option on the Carrier 30XV chiller, and show the wiring schematic.",
  },
  {
    model: "23XRV",
    title: "VFD Control Wiring Schematic",
    text: "Show the Foxboro VFD control wiring schematic and terminal connections for the 23XRV screw chiller.",
  },
  {
    model: "30RC",
    title: "Field Wiring & R-32 Protocols",
    text: "Show the typical field wiring schematic and R-32 A2L safety protocols for the 30RC scroll chiller.",
  },
  {
    model: "19XR",
    title: "Oil Pressure Specs & Wiring",
    text: "What are the lubrication oil pressure specifications and typical starter wiring for the 19XR centrifugal chiller?",
  },
];

export default function App() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      role: "assistant",
      content: `### Welcome to the Carrier Senior Field Engineering Specialist AI
Equipped with **Carrier Vector Search 2.0 (Dual-Vector Agent Retrieval)**, official Carrier technical manuals, and multimodal diagram intelligence.

**Certified Product Lines:**
* **AquaEdge® 19XR** (Centrifugal, 200–3000 Tons)
* **AquaEdge® 23XRV** (Variable-Speed Water-Cooled Screw, 250–550 Tons)
* **AquaForce® 30HX** (Compact Water-Cooled Screw, 75–265 Tons)
* **AquaForce® 30RC** (Greenspeed® Scroll, Puron Advance™ R-32 A2L, 60–150 Tons)
* **AquaForce® 30XV** (Variable-Speed Air-Cooled Screw, 140–500 Tons)

Select a chiller series below or ask any diagnostic, pinout, or schematic question.`,
      timestamp: new Date().toLocaleTimeString(),
    },
  ]);

  const [input, setInput] = useState("");
  const [selectedModel, setSelectedModel] = useState("All Models");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [liveElapsedMs, setLiveElapsedMs] = useState(0);

  // Modals and Drawers
  const [lightboxImage, setLightboxImage] = useState<{ url: string; caption?: string } | null>(null);
  const [showVisualSearchModal, setShowVisualSearchModal] = useState(false);
  const [showAuditLogs, setShowAuditLogs] = useState(false);
  const [visualQuery, setVisualQuery] = useState("");
  const [visualResults, setVisualResults] = useState<DiagramResult[]>([]);
  const [isVisualSearching, setIsVisualSearching] = useState(false);
  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>([]);

  const chatEndRef = useRef<HTMLDivElement>(null);
  const timerIntervalRef = useRef<any>(null);
  const requestStartRef = useRef<number>(0);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isGenerating, liveElapsedMs]);

  const handleResetChat = () => {
    setSessionId(null);
    setMessages([
      {
        id: "welcome",
        role: "assistant",
        content: `### Welcome to the Carrier Senior Field Engineering Specialist AI
Equipped with **Carrier Vector Search 2.0 (Dual-Vector Agent Retrieval)**, official Carrier technical manuals, and multimodal diagram intelligence.

**Certified Product Lines:**
* **AquaEdge® 19XR** (Centrifugal, 200–3000 Tons)
* **AquaEdge® 23XRV** (Variable-Speed Water-Cooled Screw, 250–550 Tons)
* **AquaForce® 30HX** (Compact Water-Cooled Screw, 75–265 Tons)
* **AquaForce® 30RC** (Greenspeed® Scroll, Puron Advance™ R-32 A2L, 60–150 Tons)
* **AquaForce® 30XV** (Variable-Speed Air-Cooled Screw, 140–500 Tons)

Select a chiller series below or ask any diagnostic, pinout, or schematic question.`,
        timestamp: new Date().toLocaleTimeString(),
      },
    ]);
  };

  // Fetch recent audit logs when drawer opens
  const fetchAuditLogs = async () => {
    try {
      const res = await fetch("http://localhost:8000/api/logs/recent?limit=25");
      const data = await res.json();
      setAuditLogs(data.logs || []);
    } catch (err) {
      console.error("Failed to fetch logs:", err);
    }
  };

  const handleSend = async (overrideText?: string, overrideModel?: string) => {
    const textToSend = overrideText || input;
    const targetModel = overrideModel !== undefined ? overrideModel : selectedModel;
    if (!textToSend.trim() || isGenerating) return;

    // Start precision turnaround timer
    const startTimestamp = performance.now();
    requestStartRef.current = startTimestamp;
    setIsGenerating(true);
    setLiveElapsedMs(0);

    const userMessage: Message = {
      id: `usr_${Date.now()}`,
      role: "user",
      content: textToSend,
      modelSeries: targetModel,
      timestamp: new Date().toLocaleTimeString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");

    // Live micro-timer ticker (every 30ms)
    timerIntervalRef.current = setInterval(() => {
      setLiveElapsedMs(Math.round(performance.now() - startTimestamp));
    }, 30);

    // Create initial assistant placeholder for streaming tokens
    const asstMsgId = `asst_${Date.now()}`;
    const initialAsstMessage: Message = {
      id: asstMsgId,
      role: "assistant",
      content: "",
      modelSeries: targetModel,
      toolsUsed: [],
      timestamp: new Date().toLocaleTimeString(),
    };

    setMessages((prev) => [...prev, initialAsstMessage]);

    try {
      const res = await fetch("http://localhost:8000/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: textToSend,
          model_series: targetModel === "All Models" ? null : targetModel,
          session_id: sessionId,
          client_send_time_ms: startTimestamp,
        }),
      });

      if (!res.ok) {
        throw new Error(`HTTP error ${res.status}: ${res.statusText}`);
      }

      if (!res.body) {
        throw new Error("No response body available for streaming.");
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let accumulatedText = "";
      let accumulatedTools: any[] = [];
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data:")) continue;
          try {
            const payload = JSON.parse(trimmed.slice(5).trim());
            if (payload.type === "init") {
              if (payload.session_id) setSessionId(payload.session_id);
            } else if (payload.type === "token") {
              accumulatedText += payload.content;
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === asstMsgId
                    ? { ...msg, content: accumulatedText }
                    : msg
                )
              );
            } else if (payload.type === "tool_call") {
              accumulatedTools.push({ tool_name: payload.tool_name, latency_ms: 0 });
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === asstMsgId
                    ? { ...msg, toolsUsed: [...accumulatedTools] }
                    : msg
                )
              );
            } else if (payload.type === "done") {
              if (payload.session_id) setSessionId(payload.session_id);
              const endTimestamp = performance.now();
              const totalTurnaroundMs = Math.round(endTimestamp - startTimestamp);
              clearInterval(timerIntervalRef.current);

              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === asstMsgId
                    ? {
                        ...msg,
                        content: accumulatedText,
                        toolsUsed: payload.tools_used && payload.tools_used.length > 0 ? payload.tools_used : accumulatedTools,
                        serverLatencyMs: payload.server_latency_ms,
                        totalLatencyMs: totalTurnaroundMs,
                      }
                    : msg
                )
              );
            } else if (payload.type === "error") {
              clearInterval(timerIntervalRef.current);
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === asstMsgId
                    ? {
                        ...msg,
                        content: `⚠️ **Server/Authentication Error**: ${payload.error}`,
                      }
                    : msg
                )
              );
              break;
            }
          } catch (e: any) {
            console.error("Error processing stream chunk:", e);
          }
        }
      }
    } catch (err: any) {
      clearInterval(timerIntervalRef.current);
      const endTimestamp = performance.now();
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === asstMsgId
            ? {
                ...msg,
                content: `⚠️ **Diagnostic Request Failed**: ${err.message}. Please verify the backend service is running on port 8000.`,
                totalLatencyMs: Math.round(endTimestamp - startTimestamp),
              }
            : msg
        )
      );
    } finally {
      setIsGenerating(false);
      setLiveElapsedMs(0);
    }
  };

  const executeVisualSearch = async (queryText?: string) => {
    const q = queryText || visualQuery;
    if (!q.trim()) return;
    setIsVisualSearching(true);
    try {
      const formData = new FormData();
      formData.append("description", q);
      if (selectedModel !== "All Models") {
        formData.append("model_series", selectedModel);
      }
      const res = await fetch("http://localhost:8000/api/visual-search", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      setVisualResults(data.diagrams || []);
    } catch (err) {
      console.error("Visual search error:", err);
    } finally {
      setIsVisualSearching(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", backgroundColor: "#f8fafc" }}>
      {/* Top Header */}
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 24px",
          backgroundColor: "#003882",
          color: "#ffffff",
          boxShadow: "0 2px 4px rgba(0,0,0,0.1)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <div
            style={{
              backgroundColor: "#ffffff",
              color: "#003882",
              padding: "6px 10px",
              borderRadius: "6px",
              fontWeight: 800,
              fontSize: "16px",
              letterSpacing: "1px",
            }}
          >
            CARRIER
          </div>
          <div>
            <h1 style={{ fontSize: "16px", fontWeight: 700, margin: 0, display: "flex", alignItems: "center", gap: "8px" }}>
              Commercial Chiller Specialist Assistant
              <span
                style={{
                  fontSize: "11px",
                  backgroundColor: "#00a3e0",
                  color: "#ffffff",
                  padding: "2px 8px",
                  borderRadius: "12px",
                  fontWeight: 600,
                }}
              >
                Vector Search 2.0
              </span>
            </h1>
            <p style={{ fontSize: "12px", opacity: 0.85, margin: 0 }}>
              ADK 2.0 Multimodal RAG • Instant kNN Visual Embeddings • Model-Filtered Diagnosis
            </p>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <button
            onClick={handleResetChat}
            title="Start a fresh conversational session"
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              padding: "6px 12px",
              backgroundColor: "rgba(255,255,255,0.15)",
              color: "#ffffff",
              border: "1px solid rgba(255,255,255,0.3)",
              borderRadius: "6px",
              fontSize: "13px",
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            <RefreshCw size={14} />
            New Chat
          </button>

          <button
            onClick={() => {
              setShowVisualSearchModal(true);
            }}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              padding: "6px 12px",
              backgroundColor: "rgba(255,255,255,0.15)",
              color: "#ffffff",
              border: "1px solid rgba(255,255,255,0.3)",
              borderRadius: "6px",
              fontSize: "13px",
              fontWeight: 500,
            }}
          >
            <ImageIcon size={15} />
            Visual Schematic Index
          </button>

          <button
            onClick={() => {
              setShowAuditLogs(true);
              fetchAuditLogs();
            }}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              padding: "6px 12px",
              backgroundColor: "rgba(255,255,255,0.15)",
              color: "#ffffff",
              border: "1px solid rgba(255,255,255,0.3)",
              borderRadius: "6px",
              fontSize: "13px",
              fontWeight: 500,
            }}
          >
            <Terminal size={15} />
            Audit Telemetry
          </button>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              padding: "4px 10px",
              backgroundColor: "#16a34a",
              borderRadius: "20px",
              fontSize: "11px",
              fontWeight: 600,
            }}
          >
            <div
              style={{
                width: "8px",
                height: "8px",
                backgroundColor: "#ffffff",
                borderRadius: "50%",
              }}
              className="pulsing-dot"
            />
            Runtime Active
          </div>
        </div>
      </header>

      {/* Model Series Selector Toolbar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          padding: "10px 24px",
          backgroundColor: "#ffffff",
          borderBottom: "1px solid #e2e8f0",
          overflowX: "auto",
        }}
      >
        <span style={{ fontSize: "12px", fontWeight: 700, color: "#64748b", textTransform: "uppercase" }}>
          Target Chiller:
        </span>
        {CARRIER_MODELS.map((m) => {
          const isSelected = selectedModel === m.id;
          return (
            <button
              key={m.id}
              onClick={() => {
                if (selectedModel !== m.id) {
                  setSelectedModel(m.id);
                  setSessionId(null);
                }
              }}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                padding: "6px 12px",
                borderRadius: "20px",
                fontSize: "13px",
                fontWeight: isSelected ? 600 : 500,
                backgroundColor: isSelected ? "#003882" : "#f1f5f9",
                color: isSelected ? "#ffffff" : "#334155",
                border: isSelected ? "1px solid #003882" : "1px solid #e2e8f0",
                transition: "all 0.15s ease",
              }}
            >
              <span>{m.label}</span>
              <span
                style={{
                  fontSize: "10px",
                  padding: "1px 6px",
                  borderRadius: "10px",
                  backgroundColor: isSelected ? "rgba(255,255,255,0.25)" : "#e2e8f0",
                  color: isSelected ? "#ffffff" : "#475569",
                }}
              >
                {m.badge}
              </span>
            </button>
          );
        })}
      </div>

      {/* Main Chat Conversation Container */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "20px 24px",
          display: "flex",
          flexDirection: "column",
          gap: "16px",
        }}
      >
        {messages.map((msg) => {
          const isUser = msg.role === "user";
          return (
            <div
              key={msg.id}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: isUser ? "flex-end" : "flex-start",
                maxWidth: "100%",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  marginBottom: "4px",
                  fontSize: "12px",
                  color: "#64748b",
                }}
              >
                {isUser ? (
                  <>
                    <span>Field Engineer</span>
                    <span>•</span>
                    <span>{msg.timestamp}</span>
                    {msg.modelSeries && msg.modelSeries !== "All Models" && (
                      <span
                        style={{
                          backgroundColor: "#e2e8f0",
                          color: "#1e293b",
                          padding: "1px 6px",
                          borderRadius: "4px",
                          fontSize: "11px",
                          fontWeight: 600,
                        }}
                      >
                        Carrier {msg.modelSeries}
                      </span>
                    )}
                  </>
                ) : (
                  <>
                    <span style={{ fontWeight: 600, color: "#003882" }}>Carrier Specialist AI</span>
                    <span>•</span>
                    <span>{msg.timestamp}</span>
                    {/* Turnaround Latency Badge */}
                    {msg.totalLatencyMs !== undefined && (
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "4px",
                          backgroundColor: msg.totalLatencyMs < 1500 ? "#ecfdf5" : "#fff7ed",
                          color: msg.totalLatencyMs < 1500 ? "#047857" : "#c2410c",
                          border: `1px solid ${msg.totalLatencyMs < 1500 ? "#a7f3d0" : "#fed7aa"}`,
                          padding: "2px 8px",
                          borderRadius: "12px",
                          fontSize: "11px",
                          fontWeight: 700,
                        }}
                        title={`Total Turnaround: ${msg.totalLatencyMs}ms (Backend: ${msg.serverLatencyMs || "N/A"}ms)`}
                      >
                        <Zap size={11} />
                        {msg.totalLatencyMs.toLocaleString()} ms Turnaround
                      </div>
                    )}
                  </>
                )}
              </div>

              {/* Message Bubble Card */}
              <div
                style={{
                  backgroundColor: isUser ? "#003882" : "#ffffff",
                  color: isUser ? "#ffffff" : "#1e293b",
                  padding: "14px 18px",
                  borderRadius: isUser ? "16px 16px 2px 16px" : "16px 16px 16px 2px",
                  maxWidth: isUser ? "80%" : "90%",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
                  border: isUser ? "none" : "1px solid #e2e8f0",
                  lineHeight: "1.6",
                }}
              >
                {/* Tool Invocations Banner */}
                {msg.toolsUsed && msg.toolsUsed.length > 0 && (
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      gap: "6px",
                      marginBottom: "12px",
                      padding: "6px 10px",
                      backgroundColor: "#f8fafc",
                      borderRadius: "6px",
                      border: "1px solid #e2e8f0",
                    }}
                  >
                    <span style={{ fontSize: "11px", fontWeight: 700, color: "#64748b" }}>Tools Executed:</span>
                    {msg.toolsUsed.map((t, i) => (
                      <span
                        key={i}
                        style={{
                          fontSize: "11px",
                          backgroundColor: "#e0f2fe",
                          color: "#0369a1",
                          padding: "2px 6px",
                          borderRadius: "4px",
                          fontWeight: 600,
                        }}
                      >
                        ⚙️ {t.tool_name}
                      </span>
                    ))}
                  </div>
                )}

                {/* Markdown Content */}
                <div className="prose prose-sm max-w-none">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      hr: ({ node, ...props }) => (
                        <hr style={{ border: "none", borderTop: "1px solid #e2e8f0", margin: "16px 0" }} {...props} />
                      ),
                      img: ({ node, ...props }) => {
                        const rawUrl = props.src || "";
                        const resolvedUrl = rawUrl.replace(
                          "https://storage.googleapis.com/genai-demos-391416-carrier-assets/",
                          "http://localhost:8000/api/image/"
                        );
                        return (
                          <div style={{ margin: "16px 0", width: "100%" }}>
                            <div
                              style={{
                                border: "1px solid #cbd5e1",
                                borderRadius: "8px",
                                overflow: "hidden",
                                backgroundColor: "#ffffff",
                                boxShadow: "0 4px 12px rgba(0,0,0,0.06)",
                                width: "100%",
                              }}
                            >
                              <div
                                style={{
                                  padding: "8px 14px",
                                  backgroundColor: "#003882",
                                  color: "#ffffff",
                                  fontSize: "13px",
                                  fontWeight: 600,
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "space-between",
                                }}
                              >
                                <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                  📐 Carrier Technical Schematic: {props.alt || "Manual Diagram"}
                                </span>
                                <a
                                  href={resolvedUrl}
                                  target="_blank"
                                  rel="noreferrer"
                                  style={{
                                    fontSize: "12px",
                                    color: "#93c5fd",
                                    textDecoration: "none",
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "4px",
                                    fontWeight: 500,
                                  }}
                                >
                                  <ExternalLink size={13} /> View Full Size
                                </a>
                              </div>
                              <div style={{ padding: "10px", backgroundColor: "#ffffff", textAlign: "center" }}>
                                <img
                                  src={resolvedUrl}
                                  alt={props.alt || "Carrier Schematic"}
                                  style={{
                                    width: "100%",
                                    maxHeight: "750px",
                                    objectFit: "contain",
                                    display: "block",
                                    margin: "0 auto",
                                  }}
                                  loading="eager"
                                />
                              </div>
                            </div>
                          </div>
                        );
                      },
                      code: ({ node, ...props }) => (
                        <code
                          style={{
                            backgroundColor: isUser ? "rgba(255,255,255,0.2)" : "#f1f5f9",
                            padding: "2px 5px",
                            borderRadius: "4px",
                            fontSize: "13px",
                            fontFamily: "monospace",
                          }}
                          {...props}
                        />
                      ),
                      table: ({ node, ...props }) => (
                        <div style={{ overflowX: "auto", margin: "16px 0", borderRadius: "8px", border: "1px solid #cbd5e1", boxShadow: "0 2px 8px rgba(0,0,0,0.05)" }}>
                          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px", textAlign: "left" }} {...props} />
                        </div>
                      ),
                      thead: ({ node, ...props }) => (
                        <thead style={{ backgroundColor: "#003882", color: "#ffffff" }} {...props} />
                      ),
                      th: ({ node, ...props }) => (
                        <th style={{ padding: "10px 14px", fontWeight: 600, borderBottom: "2px solid #00224f", whiteSpace: "nowrap" }} {...props} />
                      ),
                      td: ({ node, ...props }) => (
                        <td style={{ padding: "8px 14px", borderBottom: "1px solid #e2e8f0", verticalAlign: "top" }} {...props} />
                      ),
                      tr: ({ node, ...props }) => (
                        <tr style={{ backgroundColor: "#ffffff" }} {...props} />
                      ),
                    }}
                  >
                    {cleanMarkdown(msg.content)}
                  </ReactMarkdown>
                </div>
              </div>
            </div>
          );
        })}

        {/* Live Generation Ticker Indicator */}
        {isGenerating && (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: "6px" }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                padding: "8px 14px",
                backgroundColor: "#ffffff",
                border: "1px solid #cbd5e1",
                borderRadius: "16px",
                boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
                fontSize: "13px",
                color: "#1e293b",
              }}
            >
              <div
                style={{
                  width: "10px",
                  height: "10px",
                  borderRadius: "50%",
                  backgroundColor: "#00a3e0",
                }}
                className="pulsing-dot"
              />
              <span style={{ fontWeight: 600 }}>Diagnosing with Vector Search 2.0...</span>
              <span
                style={{
                  fontFamily: "monospace",
                  fontWeight: 700,
                  color: "#0066cc",
                  backgroundColor: "#f0fdf4",
                  padding: "2px 6px",
                  borderRadius: "4px",
                }}
              >
                ⏱️ {liveElapsedMs.toLocaleString()} ms
              </span>
            </div>
          </div>
        )}

        <div ref={chatEndRef} />
      </div>

      {/* Suggested Quick Prompt Chips */}
      <div
        style={{
          padding: "8px 24px",
          backgroundColor: "#ffffff",
          borderTop: "1px solid #e2e8f0",
          display: "flex",
          alignItems: "center",
          gap: "8px",
          overflowX: "auto",
        }}
      >
        <span style={{ fontSize: "11px", fontWeight: 700, color: "#94a3b8", whiteSpace: "nowrap" }}>
          QUICK SCENARIOS:
        </span>
        {QUICK_PROMPTS.map((p, idx) => (
          <button
            key={idx}
            onClick={() => {
              setSelectedModel(p.model);
              handleSend(p.text, p.model);
            }}
            style={{
              whiteSpace: "nowrap",
              fontSize: "12px",
              padding: "4px 10px",
              borderRadius: "12px",
              backgroundColor: "#f8fafc",
              border: "1px solid #cbd5e1",
              color: "#334155",
              display: "flex",
              alignItems: "center",
              gap: "4px",
            }}
          >
            <span
              style={{
                fontSize: "10px",
                backgroundColor: "#003882",
                color: "#ffffff",
                padding: "1px 4px",
                borderRadius: "3px",
                fontWeight: 700,
              }}
            >
              {p.model}
            </span>
            {p.title}
          </button>
        ))}
      </div>

      {/* Chat Input Bar */}
      <div
        style={{
          padding: "14px 24px",
          backgroundColor: "#ffffff",
          borderTop: "1px solid #e2e8f0",
          boxShadow: "0 -2px 8px rgba(0,0,0,0.03)",
        }}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
          style={{ display: "flex", alignItems: "center", gap: "10px" }}
        >
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={`Ask a technical question about Carrier ${selectedModel} (e.g. alarm codes, wiring pinouts, torque specs, schematics)...`}
            disabled={isGenerating}
            style={{
              flex: 1,
              padding: "12px 16px",
              borderRadius: "8px",
              border: "1px solid #cbd5e1",
              fontSize: "14px",
              outline: "none",
              backgroundColor: isGenerating ? "#f1f5f9" : "#ffffff",
            }}
          />
          <button
            type="submit"
            disabled={isGenerating || !input.trim()}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              padding: "12px 20px",
              backgroundColor: isGenerating || !input.trim() ? "#94a3b8" : "#003882",
              color: "#ffffff",
              border: "none",
              borderRadius: "8px",
              fontWeight: 600,
              fontSize: "14px",
            }}
          >
            <Send size={16} />
            Send
          </button>
        </form>
      </div>

      {/* Lightbox Modal for Schematics */}
      {lightboxImage && (
        <div
          onClick={() => setLightboxImage(null)}
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: "rgba(10, 25, 47, 0.85)",
            zIndex: 9999,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            padding: "24px",
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              backgroundColor: "#ffffff",
              borderRadius: "12px",
              padding: "16px",
              maxWidth: "92vw",
              maxHeight: "92vh",
              display: "flex",
              flexDirection: "column",
              gap: "12px",
              boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h3 style={{ fontSize: "15px", fontWeight: 700, margin: 0, color: "#003882" }}>
                {lightboxImage.caption || "High-Resolution Carrier Schematic"}
              </h3>
              <div style={{ display: "flex", gap: "8px" }}>
                <a
                  href={lightboxImage.url}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "4px",
                    padding: "4px 8px",
                    backgroundColor: "#f1f5f9",
                    borderRadius: "4px",
                    fontSize: "12px",
                    color: "#0066cc",
                    textDecoration: "none",
                  }}
                >
                  <ExternalLink size={13} /> Open Full Size
                </a>
                <button
                  onClick={() => setLightboxImage(null)}
                  style={{
                    border: "none",
                    background: "none",
                    cursor: "pointer",
                    color: "#64748b",
                  }}
                >
                  <X size={20} />
                </button>
              </div>
            </div>
            <div style={{ overflow: "auto", display: "flex", justifyContent: "center" }}>
              <img
                src={lightboxImage.url}
                alt={lightboxImage.caption || "Schematic"}
                style={{ maxHeight: "75vh", maxWidth: "100%", objectFit: "contain" }}
              />
            </div>
          </div>
        </div>
      )}

      {/* Visual Search Modal */}
      {showVisualSearchModal && (
        <div
          onClick={() => setShowVisualSearchModal(false)}
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: "rgba(0,0,0,0.6)",
            zIndex: 9000,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "24px",
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              backgroundColor: "#ffffff",
              borderRadius: "12px",
              width: "800px",
              maxWidth: "95vw",
              maxHeight: "85vh",
              display: "flex",
              flexDirection: "column",
              boxShadow: "0 10px 25px rgba(0,0,0,0.3)",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                padding: "16px 20px",
                backgroundColor: "#003882",
                color: "#ffffff",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <ImageIcon size={18} />
                <h2 style={{ fontSize: "16px", fontWeight: 700, margin: 0 }}>
                  Multimodal Visual Schematic Search (Vector Search 2.0)
                </h2>
              </div>
              <button
                onClick={() => setShowVisualSearchModal(false)}
                style={{ background: "none", border: "none", color: "#ffffff" }}
              >
                <X size={18} />
              </button>
            </div>

            <div style={{ padding: "16px 20px", borderBottom: "1px solid #e2e8f0" }}>
              <div style={{ display: "flex", gap: "8px" }}>
                <input
                  type="text"
                  value={visualQuery}
                  onChange={(e) => setVisualQuery(e.target.value)}
                  placeholder="Search schematic by caption or description (e.g. Alarm routing, oil pump wiring, Fig 51)..."
                  style={{
                    flex: 1,
                    padding: "8px 12px",
                    borderRadius: "6px",
                    border: "1px solid #cbd5e1",
                    fontSize: "14px",
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") executeVisualSearch();
                  }}
                />
                <button
                  onClick={() => executeVisualSearch()}
                  disabled={isVisualSearching || !visualQuery.trim()}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                    padding: "8px 16px",
                    backgroundColor: "#003882",
                    color: "#ffffff",
                    border: "none",
                    borderRadius: "6px",
                    fontWeight: 600,
                  }}
                >
                  <Search size={14} />
                  Search
                </button>
              </div>
            </div>

            <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px" }}>
              {isVisualSearching ? (
                <div style={{ textAlign: "center", padding: "40px 0", color: "#64748b" }}>
                  <RefreshCw size={24} className="pulsing-dot" style={{ margin: "0 auto 8px" }} />
                  <p>Searching 1,408-dimensional visual vectors...</p>
                </div>
              ) : visualResults.length > 0 ? (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "16px" }}>
                  {visualResults.map((diag, i) => {
                    const safeImgUrl = (diag.image_url || "").replace(
                      "https://storage.googleapis.com/genai-demos-391416-carrier-assets/",
                      "http://localhost:8000/api/image/"
                    );
                    return (
                      <div
                        key={i}
                        onClick={() => setLightboxImage({ url: safeImgUrl, caption: diag.caption })}
                        style={{
                          border: "1px solid #e2e8f0",
                          borderRadius: "8px",
                          overflow: "hidden",
                          cursor: "pointer",
                          backgroundColor: "#f8fafc",
                          display: "flex",
                          flexDirection: "column",
                        }}
                      >
                        <img
                          src={safeImgUrl}
                          alt={diag.caption}
                          style={{ height: "140px", width: "100%", objectFit: "contain", backgroundColor: "#ffffff" }}
                        />
                        <div style={{ padding: "8px 10px", flex: 1, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
                          <div style={{ fontSize: "12px", fontWeight: 600, color: "#1e293b", marginBottom: "4px" }}>
                          {diag.caption || "Carrier Diagram"}
                        </div>
                        <div style={{ fontSize: "11px", color: "#64748b" }}>
                          Form {diag.form_number} • Page {diag.page_number}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
              ) : (
                <div style={{ textAlign: "center", padding: "40px 0", color: "#64748b" }}>
                  <p>Enter a search phrase above to query diagrams across all Carrier manuals.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Audit Logs Drawer */}
      {showAuditLogs && (
        <div
          onClick={() => setShowAuditLogs(false)}
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: "rgba(0,0,0,0.5)",
            zIndex: 9000,
            display: "flex",
            justifyContent: "flex-end",
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              backgroundColor: "#ffffff",
              width: "560px",
              maxWidth: "90vw",
              height: "100%",
              display: "flex",
              flexDirection: "column",
              boxShadow: "-4px 0 16px rgba(0,0,0,0.15)",
            }}
          >
            <div
              style={{
                padding: "16px 20px",
                backgroundColor: "#0a192f",
                color: "#ffffff",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div>
                <h3 style={{ fontSize: "15px", fontWeight: 700, margin: 0 }}>Cloud Logging Audit Telemetry</h3>
                <p style={{ fontSize: "11px", color: "#94a3b8", margin: 0 }}>Log: carrier-agent-audit • Google Cloud</p>
              </div>
              <div style={{ display: "flex", gap: "8px" }}>
                <button
                  onClick={fetchAuditLogs}
                  style={{ background: "none", border: "none", color: "#ffffff", cursor: "pointer" }}
                >
                  <RefreshCw size={16} />
                </button>
                <button
                  onClick={() => setShowAuditLogs(false)}
                  style={{ background: "none", border: "none", color: "#ffffff", cursor: "pointer" }}
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            <div style={{ flex: 1, overflowY: "auto", padding: "16px", backgroundColor: "#0f172a", color: "#e2e8f0" }}>
              {auditLogs.length > 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                  {auditLogs.map((log, i) => (
                    <div
                      key={i}
                      style={{
                        backgroundColor: "#1e293b",
                        borderRadius: "6px",
                        padding: "10px 12px",
                        fontSize: "12px",
                        borderLeft: `3px solid ${log.severity === "ERROR" ? "#ef4444" : "#10b981"}`,
                        fontFamily: "monospace",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px", color: "#94a3b8" }}>
                        <span>{log.payload?.event_type || log.payload?.tool || "AUDIT_EVENT"}</span>
                        <span>{log.timestamp?.slice(11, 19)}</span>
                      </div>
                      <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all", fontSize: "11px", color: "#cbd5e1" }}>
                        {JSON.stringify(log.payload, null, 2)}
                      </pre>
                    </div>
                  ))}
                </div>
              ) : (
                <p style={{ textAlign: "center", color: "#94a3b8", marginTop: "40px" }}>No audit log entries recorded yet.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
