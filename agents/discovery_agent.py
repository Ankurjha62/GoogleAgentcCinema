"""Discovery Agent - decides what to verify for a release.

Input : ReleaseInfo JSON (from intake agent).
Output: JSON array of ``VerificationTarget`` objects
        [{service, kind, detail, method, path, request_body}].

Grafana MCP (optional): searches dashboards for the affected services so the
agent can ground "what healthy looks like" before tests are even generated.
"""
from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.tools.mcp_tool import McpToolset

from orchestrator.config import Config

DISCOVERY_INSTRUCTION = """You are the Discovery Agent in a test-automation pipeline.
Given a structured release description, decide what to verify.

Return ONLY a JSON array (no markdown fences) of objects with EXACTLY these keys:
[
  {
    "service": "affected service name",
    "kind": "endpoint | user_flow | data | config",
    "detail": "concise description of what to check",
    "method": "HTTP method e.g. GET, POST (kind=endpoint only)",
    "path": "URL path e.g. /api/orders (kind=endpoint only)",
    "request_body": "JSON request body as compact string, only if needed for the call"
  }
]

Rules:
- 3-6 targets max. Prefer endpoints and user flows mentioned in the release.
- The app under test is a sample e-commerce API at http://localhost:8000 with
  endpoints like /health, /products, /orders, /cart, /checkout.
- When given a taxonomy of dashboards from Grafana, note anything that should be
  actively verified via telemetry (error rates, latency) in "detail".

Use the grafana dashboard search tool when available to learn what the service
normally monitors, so targets reflect real-world observability.
"""


def build_discovery_agent(cfg: Config, grafana: McpToolset) -> LlmAgent:
    """Return the ADK LlmAgent for the discovery step (binds Grafana MCP)."""
    return LlmAgent(
        name="discovery_agent",
        model=Gemini(model=cfg.llm_model),
        static_instruction=DISCOVERY_INSTRUCTION,
        description=(
            "Determines what to verify from a release, using Grafana dashboards "
            "for context."
        ),
        tools=[grafana],
    )