"""Intake Agent - parses a raw release email into structured release info.

Input : raw email (subject + body).
Output: a single JSON object matching ``ReleaseInfo``.

Grafana MCP: none (pure NLP extraction).
"""
from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models import Gemini

from orchestrator.config import Config

INTAKE_INSTRUCTION = """You are the Intake Agent in a test-automation pipeline.
Extract structured release information from a raw release/feature email.

Return ONLY valid JSON with EXACTLY these keys and NO markdown fences:
{
  "feature_name": "short name of the feature or release",
  "description": "1-3 sentence summary of what changed",
  "affected_services": ["list", "of", "affected", "services", "or", "endpoints"],
  "release_id": "release/PR/build identifier if mentioned, else empty string",
  "sender": "sender email address if identifiable, else empty string"
}

Rules:
- Infer affected services from endpoints/paths/services mentioned in the email.
- If the email describes a UI feature, still list the services it touches.
- Never invent a release_id; leave it empty when unknown.
"""


def build_intake_agent(cfg: Config) -> LlmAgent:
    """Return the ADK LlmAgent for the intake step."""
    return LlmAgent(
        name="intake_agent",
        model=Gemini(model=cfg.llm_model),
        static_instruction=INTAKE_INSTRUCTION,
        description="Parses a release email into structured release info.",
    )