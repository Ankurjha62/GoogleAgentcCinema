"""TestMind pipeline orchestrator.

Chains the six agents in order, feeding each one's structured output to the
next. Keeps a full audit trail under storage/ and logs every stage.

Flow:
  email -> intake -> discovery -> testgen -> automation (Grafea MCP)
        -> self_healing (Grafana MCP) -> reporting (Grafana MCP)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from agents.automation_agent import build_automation_agent
from agents.discovery_agent import build_discovery_agent
from agents.intake_agent import build_intake_agent
from agents.reporting_agent import build_reporting_agent
from agents.self_healing_agent import build_self_healing_agent
from agents.testgen_agent import build_testgen_agent
from orchestrator.config import ROOT, load_config
from orchestrator.deps import build_grafana_toolset
from orchestrator.json_utils import extract_list_json, safe_loads
from orchestrator.models import ReleaseInfo, TestCase, VerificationTarget
from orchestrator.runtime import run_agent_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("testmind.pipeline")


def _persist(name: str, payload: Any) -> Path:
    cfg = load_config()
    out_dir: Path = cfg.storage_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    return path


def run_pipeline(raw_email: str) -> dict[str, Any]:
    """Execute the full email->report pipeline. Returns the run record."""
    load_dotenv(ROOT / ".env")
    cfg = load_config()

    # Prepare output dirs.
    cfg.tests_dir.mkdir(parents=True, exist_ok=True)
    cfg.storage_dir.mkdir(parents=True, exist_ok=True)

    # Single shared Grafana MCP connection.
    grafana = build_grafana_toolset(cfg)

    run_meta: dict[str, Any] = {"started_at": datetime.now(timezone.utc).isoformat()}
    try:
        # 1. Intake
        logger.info(">>> stage 1/6: intake")
        intake_text = run_agent_text(build_intake_agent(cfg), raw_email)
        release_data = safe_loads(intake_text)
        release = ReleaseInfo(**release_data) if release_data else ReleaseInfo(
            feature_name="unknown", description=intake_text[:200]
        )
        run_meta["release"] = release.model_dump()
        _persist("1_release.json", release.model_dump())

        # 2. Discovery
        logger.info(">>> stage 2/6: discovery")
        discovery_prompt = (
            "Release info (JSON):\n"
            + json.dumps(release.model_dump(), indent=2)
            + "\n\nFind what to verify. Use Grafana dashboard search first."
        )
        discovery_text = run_agent_text(
            build_discovery_agent(cfg, grafana), discovery_prompt
        )
        targets_data = extract_list_json(discovery_text)
        targets = [
            VerificationTarget(**t) if isinstance(t, dict) else t
            for t in targets_data
        ]
        run_meta["targets"] = [t.model_dump() for t in targets]
        _persist("2_targets.json", [t.model_dump() for t in targets])

        # 3. TestGen
        logger.info(">>> stage 3/6: testgen")
        testgen_prompt = (
            "Verification targets (JSON):\n"
            + json.dumps([t.model_dump() for t in targets], indent=2)
            + "\n\nGenerate concrete test cases."
        )
        testgen_text = run_agent_text(build_testgen_agent(cfg), testgen_prompt)
        cases_data = extract_list_json(testgen_text)
        cases = [TestCase(**c) if isinstance(c, dict) else c for c in cases_data]
        run_meta["test_cases"] = [c.model_dump() for c in cases]
        _persist("3_test_cases.json", [c.model_dump() for c in cases])

        # Write human-readable specs to tests_generated/
        specs_file = cfg.tests_dir / f"{release.release_id or 'run'}.tests.json"
        specs_file.write_text(
            json.dumps([c.model_dump() for c in cases], indent=2), encoding="utf-8"
        )
        run_meta["specs_path"] = str(specs_file)

        # 4. Automation
        logger.info(">>> stage 4/6: automation")
        exec_prompt = (
            "Run these test cases (JSON array):\n"
            + json.dumps([c.model_dump() for c in cases])
            + "\n\nExecute the suite, then query Grafana for evidence on failures."
        )
        automation_text = run_agent_text(
            build_automation_agent(cfg, grafana), exec_prompt
        )
        automation_data = safe_loads(automation_text) or {}
        results = automation_data.get("results", [])
        window = automation_data.get("window", {})
        telemetry = automation_data.get("telemetry", [])
        run_meta["results"] = results
        run_meta["window"] = window
        run_meta["telemetry"] = telemetry
        _persist("4_results.json", automation_data)

        # 5. Self-healing
        logger.info(">>> stage 5/6: self-healing")
        failures = [r for r in results if r.get("status") in ("FAIL", "ERROR")]
        decisions: list[dict[str, Any]] = []
        healed_results: list[dict[str, Any]] = []
        if failures:
            heal_prompt = (
                "Failed tests:\n"
                + json.dumps({"results": failures, "window": window, "telemetry": telemetry}, indent=2)
                + "\n\nDecide for each whether it is a regression or a stale test."
            )
            heal_text = run_agent_text(
                build_self_healing_agent(cfg, grafana), heal_prompt
            )
            decisions_data = safe_loads(heal_text)
            if isinstance(decisions_data, list):
                decisions = decisions_data
            elif isinstance(decisions_data, dict) and isinstance(
                decisions_data.get("decisions"), list
            ):
                decisions = decisions_data["decisions"]

            # Re-run tests whose spec was patched to match the current contract.
            cases_by_id = {c.id: c for c in cases}
            from orchestrator.test_runner import run_api_test, run_ui_test  # noqa: PLC0415

            for d in decisions:
                new_def = d.get("new_definition")
                if not isinstance(new_def, dict):
                    continue
                org = cases_by_id.get(d.get("test_id"))
                if org is None:
                    continue
                patched = TestCase(
                    **{**org.model_dump(), **new_def, "id": org.id}
                )
                verdict = str(d.get("verdict", "")).upper()
                if verdict == "REGRESSION":
                    continue  # real regression: keep the red test, escalate later
                rerun = (
                    run_ui_test(patched, cfg.sample_app_url)
                    if patched.type == "ui"
                    else run_api_test(patched, cfg.sample_app_url)
                )
                healed_results.append(rerun.model_dump())
        run_meta["decisions"] = decisions
        run_meta["healed_results"] = healed_results
        _persist("5_decisions.json", decisions)

        # 6. Reporting
        logger.info(">>> stage 6/6: reporting")
        report_payload = {
            "release": release.model_dump(),
            "all_results": results,
            "decisions": decisions,
            "healed_results": healed_results,
        }
        report_text = run_agent_text(
            build_reporting_agent(cfg, grafana),
            "Finalize the run:\n" + json.dumps(report_payload, indent=2),
        )
        report_data = safe_loads(report_text) or {}
        run_meta["report"] = report_data
        _persist("6_report.json", report_data)

        run_meta["status"] = "completed"
    except Exception as exc:  # keep the run record even on failure
        logger.exception("pipeline failed")
        run_meta["status"] = "failed"
        run_meta["error"] = str(exc)
    finally:
        try:
            grafana.close()
        except Exception:
            pass

    run_meta["finished_at"] = datetime.now(timezone.utc).isoformat()
    run_path = _persist(
        f"run_{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json", run_meta
    )
    logger.info("pipeline finished; run record at %s", run_path)
    return run_meta