"""Test runner: executes generated API test specs against the app under test.

The automation agent calls this via an ADK FunctionTool. It executes each
``TestCase`` (except type=ui, which is executed by Playwright if configured)
and records a telemetry window so the agent can later scope Grafana queries.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

from orchestrator.config import Config
from orchestrator.models import TestCase, TestResult, TestType


def _now_ns() -> int:
    return time.time_ns()


def run_api_test(case: TestCase, base_url: str) -> TestResult:
    """Execute a single API test case and return a TestResult."""
    started = time.perf_counter()
    url = f"{base_url}{case.path}"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.request(
                method=case.method,
                url=url,
                json=json.loads(case.request_body) if case.request_body else None,
            )
        passed = resp.status_code == case.expected_status
        error = None
        if not passed:
            error = (
                f"expected status {case.expected_status} got {resp.status_code}: "
                f"{resp.text[:200]}"
            )
        return TestResult(
            test_id=case.id,
            title=case.title,
            status="PASS" if passed else "FAIL",
            error=error,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:  # network / parse errors
        return TestResult(
            test_id=case.id,
            title=case.title,
            status="ERROR",
            error=f"execution error: {exc}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


def run_ui_test(case: TestCase, base_url: str) -> TestResult:
    """Execute a UI test case via Playwright if available, else skip.

    Wait, playwright import is optional; we skip with a notice when the browser
    engines are not installed so the pipeline stays headless-friendly.
    """
    started = time.perf_counter()
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(base_url)
            for step in case.flow:
                page.text_content(f"text={step}")  # basic smoke of each step
            browser.close()
        return TestResult(
            test_id=case.id,
            title=case.title,
            status="PASS",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:
        return TestResult(
            test_id=case.id,
            title=case.title,
            status="ERROR",
            error=f"ui test not executed headless: {exc}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


def run_api_suite(specs: list[TestCase | dict[str, Any]], cfg: Config) -> dict:
    """Run all API cases, returning results plus a telemetry window.

    Returns dict: {"results": [...], "window": {start_ns,end_ns,...}}
    """
    cases = [
        spec if isinstance(spec, TestCase) else TestCase(**spec) for spec in specs
    ]

    window_start = _now_ns()
    results = []
    for c in cases:
        if c.type == TestType.UI:
            results.append(run_ui_test(c, cfg.sample_app_url))
        else:
            results.append(run_api_test(c, cfg.sample_app_url))
    window_end = _now_ns()

    return {
        "results": [r.model_dump() for r in results],
        "window": {
            "start_ns": window_start,
            "end_ns": window_end,
            "started_at": datetime.fromtimestamp(
                window_start / 1e9, tz=timezone.utc
            ).isoformat(),
            "ended_at": datetime.fromtimestamp(
                window_end / 1e9, tz=timezone.utc
            ).isoformat(),
        },
        "suite_id": str(uuid4())[:8],
    }


def render_test_case(case: dict[str, Any]) -> str:
    """Render a TestCase dict into a human-readable test script (for demos)."""
    tc = TestCase(**case)
    if tc.type == "ui":
        steps = "\n".join(f"    - {s}" for s in tc.flow)
        return (
            f"# UI test {tc.id}: {tc.title}\n"
            f"# Playwright flow:\n{steps}\n"
            f"# assertions: {tc.assertions}\n"
        )
    body = f"\n    body: {tc.request_body}" if tc.request_body else ""
    return (
        f"# API test {tc.id}: {tc.title}\n"
        f"{tc.method} {tc.path}\n"
        f"    expect_status: {tc.expected_status}{body}\n"
        f"    assertions: {tc.assertions}\n"
    )