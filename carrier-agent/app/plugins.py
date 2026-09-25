"""
Carrier Agent Audit & Telemetry Plugins.
Implements Google ADK BasePlugin callbacks to provide structured logging
to Google Cloud Logging for every model call, tool execution, and turn lifecycle.
"""

import time
import os
import json
from typing import Optional, Any, Dict
from google.adk.plugins import BasePlugin
from google.adk.tools import BaseTool, ToolContext
from google.adk.agents.invocation_context import InvocationContext
from google.cloud import logging as cloud_logging

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "genai-demos-391416")

class CarrierAuditLoggingPlugin(BasePlugin):
    """Structured Cloud Logging plugin for Carrier HVAC Agent."""

    def __init__(self, project_id: str = PROJECT_ID, log_name: str = "carrier-agent-audit"):
        super().__init__(name="carrier_audit_logging")
        self.project_id = project_id
        self.log_name = log_name
        self._start_times: Dict[str, float] = {}
        try:
            self._client = cloud_logging.Client(project=project_id)
            self._logger = self._client.logger(log_name)
        except Exception as e:
            self._logger = None
            print(f"[Warn] Could not initialize Cloud Logging: {e}")

    def _log(self, event_type: str, data: Dict[str, Any], severity: str = "INFO"):
        payload = {
            "service": "carrier-chiller-agent",
            "plugin": "CarrierAuditLoggingPlugin",
            "event_type": event_type,
            "timestamp": time.time(),
            **data
        }
        if self._logger:
            try:
                self._logger.log_struct(payload, severity=severity)
            except Exception as e:
                print(f"[Logging Warn] Failed to log struct: {e}")
        else:
            print(f"[LOG {severity}] {json.dumps(payload)}")

    async def before_run_callback(self, *, invocation_context: InvocationContext) -> None:
        session_id = getattr(invocation_context, "session_id", "default_session")
        self._start_times[f"run_{session_id}"] = time.time()
        self._log("RUN_STARTED", {
            "session_id": session_id,
            "agent_name": getattr(invocation_context.agent, "name", "root_agent"),
        })

    async def after_run_callback(self, *, invocation_context: InvocationContext) -> None:
        session_id = getattr(invocation_context, "session_id", "default_session")
        key = f"run_{session_id}"
        elapsed_ms = (time.time() - self._start_times.pop(key, time.time())) * 1000
        self._log("RUN_COMPLETED", {
            "session_id": session_id,
            "turnaround_latency_ms": round(elapsed_ms, 2)
        })

    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
    ) -> Optional[dict]:
        tool_name = getattr(tool, "name", str(tool))
        self._start_times[f"tool_{tool_name}"] = time.time()
        self._log("TOOL_EXECUTION_BEFORE", {
            "tool_name": tool_name,
            "tool_args": tool_args
        })
        return None

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: Any,
    ) -> Optional[Any]:
        tool_name = getattr(tool, "name", str(tool))
        key = f"tool_{tool_name}"
        elapsed_ms = (time.time() - self._start_times.pop(key, time.time())) * 1000
        
        result_preview = str(result)[:300] if result else ""
        self._log("TOOL_EXECUTION_AFTER", {
            "tool_name": tool_name,
            "latency_ms": round(elapsed_ms, 2),
            "result_preview": result_preview
        })
        return None
