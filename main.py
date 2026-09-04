#!/usr/bin/env python
"""TestMind - email-triggered agentic test automation.

Usage:
    python main.py demo          # run the full pipeline on a sample release email
    python main.py email         # poll Gmail (app password) and run the pipeline
    python main.py sample-app    # launch the sample app under test (:8000)

Environment is read from `.env` (GEMINI_API_KEY, GRAFANA_URL,
GRAFANA_SERVICE_ACCOUNT_TOKEN, GMAIL_USER, GMAIL_APP_PASSWORD).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the project importable when run as a script.
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from orchestrator.config import load_config
from orchestrator.pipeline import run_pipeline
from trigger.gmail_watcher import fetch_release_emails, sample_email


def cmd_demo() -> int:
    print("=== TestMind demo: sample release email -> pipeline ===")
    run = run_pipeline(sample_email())
    print(f"\nPipeline status: {run.get('status')}")
    if run.get("results"):
        for r in run["results"]:
            print(f"  {r.get('test_id')}: {r.get('status')}"
                  + (f"  ({r.get('error', '')[:80]})" if r.get("error") else ""))
    if run.get("decisions"):
        print("Heal decisions:")
        for d in run["decisions"]:
            print(f"  {d.get('test_id')}: {d.get('verdict')} patched={d.get('patched')}")
    if run.get("report"):
        print(f"Report: {run['report'].get('report_path')}")
    return 0 if run.get("status") == "completed" else 1


def cmd_email() -> int:
    cfg = load_config()
    print("=== TestMind: polling Gmail for release emails ===")
    emails = fetch_release_emails(cfg)
    if not emails:
        print("No release emails found in inbox.")
        return 0
    print(f"Found {len(emails)} release email(s).")
    for em in emails:
        print(f"\n--- {em['subject']} ---")
        combined = f"Subject: {em['subject']}\n\n{em['body']}"
        run = run_pipeline(combined)
        print(f"Pipeline status: {run.get('status')}")
    return 0


def cmd_sample_app() -> int:
    import uvicorn

    print("Starting sample app at http://localhost:8000 ...")
    print("(OpenTelemetry/Grafana shipping is a stretch goal - app runs standalone)")
    uvicorn.run("sample_app.app:app", host="127.0.0.1", port=8000, reload=False)
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "demo"
    if cmd == "demo":
        return cmd_demo()
    if cmd == "email":
        return cmd_email()
    if cmd in ("sample-app", "app"):
        return cmd_sample_app()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())