"""Structured data contracts passed between TestMind agents.

Keeping these as pydantic models (not raw dicts) means each agent hands the
next one a validated schema, which makes the self-healing agent's job of
patching a single test-case trivial vs. regenerating whole scripts.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _LenientModel(BaseModel):
    """Base model that ignores unknown keys from LLM output."""

    model_config = ConfigDict(extra="ignore")


class TestType(str, Enum):
    API = "api"
    UI = "ui"


class ReleaseInfo(_LenientModel):
    """Parsed output of the intake agent (from the trigger email)."""

    feature_name: str
    description: str
    affected_services: list[str] = Field(default_factory=list)
    release_id: str = ""
    sender: str = ""
    received_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class VerificationTarget(_LenientModel):
    """A concrete "thing to verify" produced by the discovery agent."""

    service: str
    kind: str = "endpoint"  # endpoint | user_flow | data | config
    detail: str
    method: str = "GET"
    path: str = ""
    request_body: Optional[str] = None


class TestCase(_LenientModel):
    """Single concrete test case (in YAML/JSON form, renderable to code)."""

    id: str
    title: str
    type: TestType = TestType.API
    service: str
    method: str = "GET"
    path: str = ""
    request_body: Optional[str] = None
    expected_status: int = 200
    assertions: list[str] = Field(default_factory=list)
    flow: list[str] = Field(default_factory=list)  # UI steps
    severity: str = "P1"

    @field_validator("path", mode="before")
    @classmethod
    def _norm_path(cls, v):
        return v or ""

    @field_validator("type", mode="before")
    @classmethod
    def _norm_type(cls, v):
        if isinstance(v, str):
            return v.lower()
        return v

    @field_validator("request_body", mode="before")
    @classmethod
    def _norm_request_body(cls, v):
        return v or None

    @field_validator("title", mode="before")
    @classmethod
    def _norm_title(cls, v):
        return v or f"test {v or ''}"

    @field_validator("id", mode="before")
    @classmethod
    def _norm_id(cls, v):
        return v or "TC-X"

    @field_validator("flow", mode="before")
    @classmethod
    def _norm_flow(cls, v):
        return v or []

    @field_validator("assertions", mode="before")
    @classmethod
    def _norm_assertions(cls, v):
        return v or []

    @field_validator("service", mode="before")
    @classmethod
    def _norm_service(cls, v):
        return v or "unknown-service"

    @field_validator("severity", mode="before")
    @classmethod
    def _norm_severity(cls, v):
        return v or "P1"

    @field_validator("method", mode="before")
    @classmethod
    def _norm_method(cls, v):
        return v or "GET"

    @field_validator("expected_status", mode="before")
    @classmethod
    def _norm_status(cls, v):
        return v or 200


class TelemetryWindow(_LenientModel):
    """Start/end timestamp of a test run, used to scope Grafana queries."""

    start_ns: int
    end_ns: int
    started_at: str
    ended_at: str


class TestResult(_LenientModel):
    """Result of a single executed test case."""

    test_id: str
    title: str
    status: str = "FAIL"  # PASS | FAIL | ERROR
    error: Optional[str] = None
    duration_ms: int = 0
    telemetry: Optional[dict] = None  # whatever Grafana MCP returned


class HealDecision(_LenientModel):
    """Decision of the self-healing agent for a failing test."""

    test_id: str
    verdict: str  # STALE_SELECTOR | CONTRACT_CHANGED | REAL_REGRESSION | UNKNOWN
    reason: str
    patched: bool = False
    new_definition: Optional[dict] = None  # patched TestCase as dict
    escalated: bool = False
    escalation_note: Optional[str] = None