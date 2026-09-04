"""Central configuration loader for TestMind.

Loads secrets from ``.env`` and exposes a typed ``Config`` object describing the
Grafana instance, MCP connectivity, the LLM, and the app under test.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent


class Config(BaseModel):
    """Runtime configuration derived from environment variables."""

    gemini_api_key: str

    grafana_url: str
    grafana_service_account_token: str

    mcp_server_url: Optional[str] = None  # hosted mcp.grafana.com (OAuth) if set
    mcp_grafana_url_env: Optional[str] = None  # GRAFANA_URL injected into stdio server
    mcp_sa_token_env: Optional[str] = None  # token injected into stdio server

    gmail_user: str
    gmail_app_password: str

    llm_model: str = "gemini-3.5-flash-lite"
    sample_app_url: str = "http://localhost:8000"

    storage_dir: Path = ROOT / "storage"
    tests_dir: Path = ROOT / "tests_generated"
    reports_dir: Path = ROOT / "reports"


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def load_config() -> Config:
    """Load (and merge) the project .env, then build a Config."""
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / ".env.local", override=False)

    return Config(
        gemini_api_key=_env("GEMINI_API_KEY"),
        grafana_url=_env("GRAFANA_URL"),
        grafana_service_account_token=_env("GRAFANA_SERVICE_ACCOUNT_TOKEN"),
        mcp_server_url=_env("MCP_ENDPOINT") or None,
        gmail_user=_env("GMAIL_USER"),
        gmail_app_password=_env("GMAIL_APP_PASSWORD"),
        llm_model=_env("LLM_MODEL", "gemini-3.5-flash-lite"),
        sample_app_url=_env("SAMPLE_APP_URL", "http://localhost:8000"),
    )
