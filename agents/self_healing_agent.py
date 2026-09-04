"""Self-Healing Agent - decides whether a test failure is a real regression or
a stale test, using Grafana traces and alerts.

Input : JSON {"results": [...], "window": {...}, "telemetry": [...]} for FAILED tests.
Tools : Grafana MCP Tempo trace search + alert list tools.
Output: JSON array of ``HealDecision`` objects.

Decision logic (the "wow" moment):
  test failed -> check Grafana alerts for the service
    -> alert already firing ?  REAL_REGRESSION -> escalate (do NOT heal)
    -> no alert but trace shows app-side error ? REAL_REGRESSION -> escalate
    -> otherwise (no app-side evidence)  -> STALE_SELECTOR/CONTRACT_CHANGED -> patch
"""
from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.tools.mcp_tool import McpToolset

from orchestrator.config import Config

SELF_HEALING_INSTRUCTION = """You are the Self-Healing Agent in a test-automation pipeline.

You receive JSON describing failed tests: {"results":[...], "window":{...}, "telemetry":[...]}.

For EACH failed test you MUST use Grafana MCP tools BEFORE deciding:
1. The Grafana alert tools (e.g. list_alert_groups / get_alert_group or
   alertmanager_v1_list_alerts) - is there already a firing alert for the service?
2. The Tempo trace search tool (e.g. tempo_traceql-search or
   tempo_service_search_traces) - pull the trace for the failing request to see
   whether the app itself errored during the window.

Then apply this decision table:
- alert IS firing for the service OR trace shows an app-side error
    -> verdict REAL_REGRESSION, escalated=true, patched=false
- no alert and no app-side error evidence
    -> verdict STALE_SELECTOR (UI) or CONTRACT_CHANGED (API),
       patched=true (propose a corrected HTTP method / path / expected_status
       or corrected selector in new_definition), escalated=false

Return ONLY a JSON array (no markdown fences):
[
  {
    "test_id": "TC-n",
    "verdict": "STALE_SELECTOR | CONTRACT_CHANGED | REAL_REGRESSION | UNKNOWN",
    "reason": "what Grafana evidence led to this decision",
    "patched": true|false,
    "new_definition": { "path": "...", "method": "...", "expected_status": ... },
    "escalated": true|false,
    "escalation_note": "text used if escalated, else null"
  }
]
Never claim a Grafana tool returned data it did not. If Grafana is unreachable,
verdict UNKNOWN and keep escalated=false.
"""


def build_self_healing_agent(cfg: Config, grafana: McpToolset) -> LlmAgent:
    """Return the ADK LlmAgent for the self-healing step (binds Grafana MCP)."""
    return LlmAgent(
        name="self_healing_agent",
        model=Gemini(model=cfg.llm_model),
        static_instruction=SELF_HEALING_INSTRUCTION,
        description=(
            "Diagnoses failing tests against Grafana traces/alerts and decides "
            "whether to patch the test or escalate."
        ),
        tools=[grafana],
    )