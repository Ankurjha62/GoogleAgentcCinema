"""TestGen Agent - turns discovery targets into concrete test cases.

Input : JSON array of VerificationTarget objects (from discovery agent).
Output: JSON array of ``TestCase`` objects, also written to tests_generated/.

Grafana MCP: none (pure generation task).
"""
from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models import Gemini

from orchestrator.config import Config

TESTGEN_INSTRUCTION = """You are the TestGen Agent in a test-automation pipeline.
Given "things to verify", generate concrete, executable test cases.

Return ONLY a JSON array (no markdown fences) of objects with EXACTLY these keys:
[
  {
    "id": "TC-<n> (sequential)",
    "title": "short human readable title",
    "type": "api | ui",
    "service": "service under test",
    "method": "GET | POST | PUT | DELETE (for api tests)",
    "path": "URL path",
    "request_body": "compact JSON body string if needed, e.g. {\"qty\":2}",
    "expected_status": 200,
    "assertions": ["list of assertions as strings, e.g. 'response contains field products'"],
    "flow": ["UI step list, only for type=ui"],
    "severity": "P1 | P2 (P1 for critical path)"
  }
]

Rules:
- The app under test is http://localhost:8000. Known endpoints: /health (200),
  /products (200, JSON array), /products/{id} (200/404), POST /cart, GET /cart,
  POST /checkout, GET /orders.
- Keep specs in intermediate JSON form (do NOT write full scripts yourself);
  the executor at runtime rendures them.
- Always include a /health smoke test as TC-1 unless the target overrides it.
- Never fabricate a path that is not implied by the target detail.
"""


def build_testgen_agent(cfg: Config) -> LlmAgent:
    """Return the ADK LlmAgent for the test-generation step."""
    return LlmAgent(
        name="testgen_agent",
        model=Gemini(model=cfg.llm_model),
        static_instruction=TESTGEN_INSTRUCTION,
        description=(
            "Generates concrete API/UI test cases from discovery targets."
        ),
    )