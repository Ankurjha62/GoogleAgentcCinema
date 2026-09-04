# TestMind — Development Journal & Decisions

Google Agentic Cinema Hackathon · Partner: Grafana Labs
This file documents **how** TestMind was built and **why** specific paths were
chosen, so the rationale behind every engineering decision survives the
hackathon. `DevelopmentNotes.md` is the original plan; this is the log of what
actually got built and the reasoning that shaped it.

---

## 1. Architecture: email in, Grafana-backed report out

Six independent ADK agents are chained sequentially by
`orchestrator/pipeline.py`. Each stage writes its structured output to
`storage/` before the next stage reads it, giving a full audit trail:

```
release email
   -> intake        parse release info (pure LLM, JSON out)
   -> discovery     what to verify + Grafana dashboard context  [MCP]
   -> testgen       concrete API/UI test specs (JSON, not scripts)
   -> automation    executes suite + queries Grafana telemetry   [MCP]
   -> self_healing  triage failures vs Grafana alerts/traces     [MCP]
   -> reporting     Markdown report + Grafana annotation         [MCP]
```

**Why JSON specs instead of generated code?** Speeding the self-healing loop.
Patching a declarative `{path, method, expected_status}` blob is cheap; the
heal agent outputs a `new_definition` patch that we merge into the failing
`TestCase` and re-run immediately — no code regeneration, no compiler.

**Why a Python executor (`orchestrator/test_runner.py`) instead of letting the
LLM drive HTTP?** Deterministic assertions (status codes) with wall-clock
telemetry windows recorded around execution, so Grafana queries are scoped to
the exact test-run window.

---

## 2. Grafana MCP: the chosen path and why

We **self-host `grafana/mcp-grafana` over stdio with a service-account token**
instead of using the hosted `https://mcp.grafana.com/mcp` endpoint.

| Option | Auth | Headless automation |
| --- | --- | --- |
| Hosted `mcp.grafana.com` | Interactive browser OAuth | No — needs a human at a keyboard |
| Self-hosted `mcp-grafana` (Docker/`uv tool run`) | `GRAFANA_SERVICE_ACCOUNT_TOKEN` | Yes — the "email arrives, pipeline runs" story works for real |

We inject `GRAFANA_URL` and `GRAFANA_SERVICE_ACCOUNT_TOKEN` as **environment
variables into the spawned stdio server process** (`orchestrator/deps.py`).
No keys live in config files; the process inherits them per run.

Runtime wiring in `deps.py`:

```python
McpToolset(
    connection_params=StdioConnectionParams(
        command="uv", args=["tool", "run", "mcp-grafana"],
    ),
    env={"GRAFANA_URL": cfg.grafana_url,
         "GRAFANA_SERVICE_ACCOUNT_TOKEN": cfg.grafana_service_account_token},
    tool_list_cache_ttl_seconds=60.0,
    tool_filters={"grafana_query_prometheus", ...},
)
```

### Key discoveries (all verified against the live stack)
- The OSS server connects to a Grafana Cloud stack and registers **proxied
  tools**: `tools=9` for this stack (Prometheus, Loki, Tempo, dashboards,
  annotations, OnCall alert groups, incidents, user info, deeplink), totalling
  **81** tool names — but only ~21 list with our allowlist filter.
- Proxied tools carry a `grafana_` prefix (e.g. `grafana_query_prometheus`,
  `grafana_tempo_traceql-search`), which is why `tool_filters=None` vs `[]`
  matters — `None` keeps the default allowlist, `[]` disables filtering.
- A **service-account token + `uv tool run mcp-grafana` binary already on the
  machine** means zero Docker, zero browser auth. The token is scoped
  read/write for the stack; only the parts needed by the agents are allowlisted.
- Real calls during a run were proven end-to-end (OnCall `alert_groups` query,
  Tempo trace search, and Prometheus/Loki queries returned live data). This is
  the judged "actively uses Grafana Cloud MCP at runtime" requirement.

---

## 3. Model and quota strategy (hard-won)

- **Default model: `gemini-3.5-flash-lite`** (`config.py`, overridable via
  `LLM_MODEL`). Picked after `gemini-3.5-flash` returned HTTP 503 (high
  demand) and `gemini-2.5-flash` exhausted its **free-tier daily quota of 20
  requests** mid-demo — each model has a separate quota bucket, so switching
  models avoids the wall.
- `gemini-2.5-flash-lite` returned 404 "no longer available to new users";
  `gemini-3.5-flash-lite` responds correctly and is cheap.
- **429 resilience:** `orchestrator/runtime.py` wraps every agent run in a
  retry loop (sleep 45s between attempts, 3 attempts) so transient rate limits
  don't kill a demo run.

---

## 4. ADK/MCP integration gotchas (each cost a debug cycle)

1. **`instruction=` renders `{var}` templates.** Any JSON example containing
   braces (e.g. `{"id": "..."}`) crashes the agent construction. All six
   agents use `static_instruction=` instead.
2. **`mcp` SDK must be `< 2`.** `google-adk 2.8.0` imports from
   `mcp.shared.session`; `mcp 2.1.1` breaks it. Pinned `mcp==1.29.1`.
3. **Session methods are async.** `InMemorySessionService.create_session` /
   `delete_session` return coroutines; `Runner.run_async` is an async
   generator. `runtime.py` is fully async behind an `asyncio.run` wrapper.
4. **`McpToolset(tool_list_cache_ttl_seconds=0)`** raises
   `ValueError: ... must be positive` → use `60.0`.
5. **Fresh session per stage, one shared toolset.** A single Grafana
   `McpToolset` is built once and reused across stages (keeps one stdio
   server alive); each stage gets a brand-new ADK session. The stderr
   "original event loop is closed" cleanup warning is benign — the next stage
   reconnects its own stdio session.
6. **LLM JSON is messy:** fences, trailing prose, `null` fields, inconsistent
   enums (`"UI"` vs `"ui"`). `json_utils.safe_loads` / `extract_list_json`
   tolerate it; `models.py` uses `_LenientModel(extra="ignore")` and field
   validators that normalize `None` → sensible defaults and lowercase enums.

---

## 5. Test execution & self-healing loop

- **API tests** run via `httpx` against `SAMPLE_APP_URL`; **UI tests** run via
  Playwright/Chromium headless when installed (nice bonus: the UI test case
  actually navigates the sample shop).
- A "telemetry window" (`start_ns`/`end_ns`) is recorded around the suite run
  and passed to the automation + healing agents so Grafana queries are
  correctly scoped.
- **Heal step:** the self-healing agent inspects a failure, cross-checks
  Grafana (no firing alert? no error trace? then it's a stale test, not a
  regression), and either emits `new_definition` (patched spec) or
  `escalated=true`. The pipeline applies accepted patches and **re-runs the
  affected test immediately**, recording `healed_results` that land in the
  report. In the verified run, TC-2/TC-4 went FAIL → CONTRACT_CHANGED(patched)
  → PASS on re-run.
- **Persistence:** `storage/1_release.json` … `6_report.json` plus
  `run_*.json` and `reports/report-*.md`.

---

## 6. Environment & reproducibility

- Windows/PowerShell, **Python 3.13.14**, venv at `venv/`.
- `requirements.txt` pins: `google-adk>=2.8.0`, `mcp<2`, `python-dotenv`,
  `pydantic>=2.12`, `httpx`, `requests`, `google-genai`, `playwright>=1.50`,
  `PyYAML`.
- Grafana MCP binary: `uv tool install mcp-grafana` (v1.3.0), spawned at
  runtime via `uv tool run mcp-grafana`. (Note: `~/.local/bin` may not be on
  PATH; `uv tool run` resolves it anyway.)
- Secrets live only in `.env` (loaded via `python-dotenv`), which is
  git-ignored. `.env.example` is the safe template.
- Run the demo: starts the sample app with `uvicorn`, then
  `python main.py demo` (uses a canned release email; the Gmail trigger is
  opt-in).

---

## 7. What "done" looks like (verified 2026-09-05)

`python main.py demo` runs **status: completed** end-to-end:
5 tests executed, failures triaged against real Grafana data,
auto-patched and re-run, Markdown report written to `reports/`. Log lines
visible in the run: OnCall alert-group query, Tempo trace search, and
Prometheus/Loki queries during automation + healing stages.

Remaining stretch: Grafana dashboard **annotation** write is bound but not
shown in the recorded run (write tool exists; annotate-at-import-time is the
natural next wiring), and Gmail IMAP trigger is implemented but secondary to
the canned demo email.

---

## 8. Decision summary

| Decision | Choice | Why |
| --- | --- | --- |
| MCP server | self-hosted `mcp-grafana` stdio + SA token | headless automation, no OAuth human-in-loop |
| MCP client | ADK `McpToolset` proxied into each agent | native, per-agent tool visibility for the demo |
| LLM | `gemini-3.5-flash-lite` (env-overridable) | quota headroom, availability, cost |
| Test format | declarative JSON specs + Python executor | fast patching/re-run vs regenerating scripts |
| Agent chain | 6 LlmAgents, one session each, shared toolset | audit trail + isolated failures |
| Trigger | canned email first, Gmail IMAP second | demo determinism; live email is the stretch |