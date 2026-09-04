"""Automation Agent - executes generated tests and rounds them with telemetry.

Input : JSON array of TestCase objects + a note to run them.
Tools : run_test_suite (FunctionTool) + Grafana MCP metrics/logs tools.
Output: JSON {"results": [...], "window": {...}, "telemetry": {...}, "conclusion": "..."}

This is the first place the pipeline talks to Grafana at runtime: for every
failure the agent queries PromQL metrics and LogQL logs for the affected
service over the test-run window, turning "test failed" into
"test failed AND here's the production-side evidence".
"""
from __future__ import annotations

import json
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.mcp_tool import McpToolset

from pathlib import Path

from orchestrator.config import Config, load_config
from orchestrator.json_utils import safe_loads
from orchestrator.test_runner import run_api_suite

AUTOMATION_INSTRUCTION = """You are the Automation Agent in a test-automation pipeline.

You receive a JSON array of test case specs and MUST:
1. Call the 'run_test_suite' tool with the specs JSON (as a JSON string argument).
2. For EVERY failed test, call the Grafana MCP tools BEFORE concluding:
   - the PromQL metrics query tool (e.g. query_prometheus) for error rate or
     latency of the affected service over the returned telemetry window.
   - the Loki logs query tool (e.g. query_loki_logs) for error-level log lines
     in the same window.
   Use the 'from', 'to' options from the telemetry window (nanoseconds).
3. Return ONLY valid JSON and no markdown fences:
{
  "results": [ ...same result items... ],
  "window": { ...telemetry window... },
  "telemetry": [ {"test_id": "...", "metrics": "...", "logs": "..."} ],
  "conclusion": "one sentence in plain English summarizing pass/fail and evidence"
}
Do not fabricate Grafana responses: only report what the MCP tools actually
returned. If Grafana is unreachable, note it in telemetry as 'grafana unreachable'.
"""


def run_test_suite(specs_json: str) -> dict[str, Any]:
    """Run the generated test suite; returns results + telemetry window.

    Tolerates imperfect LLM-serialized JSON and falls back to the specs file
    written by the pipeline if the argument cannot be parsed.
    """
    cfg = load_config()
    specs = safe_loads(specs_json) if specs_json else None
    if isinstance(specs, dict) and "test_cases" in specs:
        specs = specs["test_cases"]
    if not isinstance(specs, list) or not specs:
        fallback = cfg.storage_dir / "3_test_cases.json"
        if fallback.exists():
            specs = json.loads(fallback.read_text(encoding="utf-8"))
    return run_api_suite(specs or [], cfg)


def build_automation_agent(cfg: Config, grafana: McpToolset) -> LlmAgent:
    """Return the ADK LlmAgent for the execution step (binds Grafana MCP)."""
    return LlmAgent(
        name="automation_agent",
        model=Gemini(model=cfg.llm_model),
        static_instruction=AUTOMATION_INSTRUCTION,
        description=(
            "Executes generated test cases and queries Grafana metrics/logs "
            "for evidence on failures."
        ),
        tools=[FunctionTool(func=run_test_suite), grafana],
    )