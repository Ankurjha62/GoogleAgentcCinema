"""Reporting Agent - writes the run summary and annotates Grafana.

Input : JSON {"release":{...}, "all_results":[...], "decisions":[...], "report_markdown_path":"..."}.
Tools : Grafana MCP dashboard annotation tool.
Output: JSON {"summary": "...", "grafana_annotation": "...", "report_path": "..."}

This replaces the old "Test Manager Dashboard": instead of a bespoke UI, the
result is pushed directly into the Grafana dashboard the team already watches.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.mcp_tool import McpToolset

from orchestrator.config import Config, load_config

REPORTING_INSTRUCTION = """You are the Reporting Agent in a test-automation pipeline.

You receive JSON describing a completed run:
{"release": {...}, "all_results": [...], "decisions": [...], "report_path": "..."}

Your tasks:
1. Call 'write_report' with the JSON (as a string) - this writes a Markdown
   report file and returns its path plus a summary line.
2. If any test was escalated (REAL_REGRESSION), call the Grafana annotation
   tool (e.g. create_annotation / dashboard_annotations_create) to annotate the
   dashboard for the affected service at the run time with a short text like
   "TestMind: N test(s) failed - REAL_REGRESSION detected" and a link to the report.
3. Return ONLY valid JSON:
{
  "summary": "2-line plain-English summary of the run",
  "grafana_annotation": "what was annotated or 'skipped - no annotation text'",
  "report_path": "absolute path to the report markdown file"
}
"""


def write_report(run_json: str) -> dict:
    """ADK FunctionTool: render the final Markdown report from run data."""
    data = json.loads(run_json)
    cfg = load_config()
    reports_dir: Path = cfg.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)

    release = data.get("release", {})
    results = data.get("all_results", [])
    decisions = data.get("decisions", [])
    healed_results = data.get("healed_results", [])

    passed = sum(1 for r in results if r.get("status") == "PASS")
    failed = sum(1 for r in results if r.get("status") == "FAIL")
    errors = sum(1 for r in results if r.get("status") == "ERROR")
    escalated = sum(1 for d in decisions if d.get("escalated"))
    healed = sum(1 for r in healed_results if r.get("status") == "PASS")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    fname = f"report-{stamp}.md"
    path = reports_dir / fname

    lines = [
        "# TestMind Run Report",
        "",
        f"- **Feature:** {release.get('feature_name', 'unknown')}",
        f"- **Release ID:** {release.get('release_id', '-')}",
        f"- **Generated:** {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Summary",
        "",
        f"**{passed} passed / {failed} failed / {errors} errored** "
        f"across {len(results)} test(s). Escalations: {escalated}.",
        "",
        "## Test Results",
        "",
        "| ID | Title | Status | Error |",
        "|----|-------|--------|-------|",
    ]
    for r in results:
        err = _md_escape(r.get("error") or "")
        lines.append(
            f"| {r.get('test_id')} | {_md_escape(r.get('title', ''))} | "
            f"{r.get('status')} | {err} |"
        )

    lines += ["", "## self-Healing Decisions", ""]
    if decisions:
        lines += ["| Test | Verdict | Patched | Escalated | Reason |", "|------|---------|---------|-----------|--------|"]
        for d in decisions:
            lines.append(
                f"| {d.get('test_id')} | {d.get('verdict')} | {d.get('patched')} "
                f"| {d.get('escalated')} | {_md_escape(d.get('reason', ''))} |"
            )
    else:
        lines.append("_No failures, no heal decisions._")

    if healed_results:
        lines += ["", "## re-run After Patching (self-healing)", ""]
        lines += ["| ID | Title | Status | Error |", "|----|-------|--------|-------|"]
        for r in healed_results:
            err = _md_escape(r.get("error") or "")
            lines.append(
                f"| {r.get('test_id')} | {_md_escape(r.get('title', ''))} | "
                f"{r.get('status')} | {err} |"
            )

    content = "\n".join(lines) + "\n"
    path.write_text(content, encoding="utf-8")

    summary = (
        f"{passed} passed, {failed} failed, {errors} errored "
        f"({healed} healed after patching). Escalations: {escalated}."
    )
    return {"summary": summary, "report_path": str(path)}


def _md_escape(text: str) -> str:
    return re.sub(r"[\r\n|]", " ", text)


def build_reporting_agent(cfg: Config, grafana: McpToolset) -> LlmAgent:
    """Return the ADK LlmAgent for the reporting step (binds Grafana MCP)."""
    return LlmAgent(
        name="reporting_agent",
        model=Gemini(model=cfg.llm_model),
        static_instruction=REPORTING_INSTRUCTION,
        description=(
            "Writes the Markdown run report and annotates Grafana dashboards."
        ),
        tools=[FunctionTool(func=write_report), grafana],
    )