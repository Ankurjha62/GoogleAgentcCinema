
# TestMind — Development Notes

### Google Agentic Cinema Hackathon · Partner: Grafana Labs

### Stack: Google ADK (Python) + Grafana Cloud MCP 

## 1. What we're building

An email-triggered, multi-agent test automation pipeline. A release/feature
email lands → agents discover what changed → generate test cases → execute
them → self-heal on failure using live Grafana telemetry → report results
back with links into Grafana dashboards.

**Hackathon requirement to keep front-of-mind:** the judged criterion is that
your project *actively uses the Grafana Cloud MCP server at runtime* — not
just AI Observability. Every agent section below flags exactly which MCP
tool calls satisfy that requirement, so you can point to them directly in
your demo video and README.

---

## 2. Tech stack

| Layer                                          | Choice                                                                                                                      | Why                                                                                  |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Agent framework                                | Google Agent Development Kit (ADK), Python                                                                                  | Native Grafana Cloud MCP support, first-party for this hackathon track               |
| Trigger                                        | Gmail API push notification (Pub/Sub) or IMAP poll                                                                          | Replaces the "developer email" trigger from the old UiPath flow                      |
| Task coordination                              | Google Cloud Pub/Sub or Cloud Tasks                                                                                         | Replaces UiPath Orchestrator Queue                                                   |
| Test execution                                 | Playwright (Python) for UI,`requests`/`httpx` for API tests                                                             | Cheap, fast, no RPA license                                                          |
| Observability data source                      | Grafana Cloud (Mimir/Prometheus for metrics, Loki for logs, Tempo for traces)                                               | Required partner integration                                                         |
| MCP transport                                  | Hosted`https://mcp.grafana.com/mcp` (dev) → self-hosted `grafana/mcp-grafana` + service account (prod/demo automation) | Hosted needs interactive OAuth; self-hosted supports headless service-account tokens |
| Agent observability (optional but recommended) | Grafana Cloud AI Observability SDK (OpenTelemetry)                                                                          | Shows judges your agent's own LLM calls/cost/latency                                 |
| Storage                                        | Firestore or a simple Postgres instance                                                                                     | Test case store, run history                                                         |
| Reporting output                               | Grafana dashboard annotations + a generated Markdown/HTML report                                                            | Replaces "Test Manager Dashboard" from UiPath version                                |

---

## 3. Environment setup (do this first, in order)

1. **Grafana Cloud account** — sign up free tier at grafana.com/products/cloud.
   Whoever creates it is the stack admin by default (Editor role, needed for
   MCP).
2. **Accept the Grafana Assistant terms** — one-time, done by the stack admin,
   required before *any* MCP tool call will work. Do this before you write a
   line of agent code, or you'll debug the wrong thing later.
3. **Explore MCP tools manually first.** Point Claude Desktop or the Gemini
   CLI at `https://mcp.grafana.com/mcp` with header
   `X-Grafana-URL: https://<your-stack>.grafana.net`, authorize via OAuth,
   and browse the 60+ tools. Note the exact tool names for: PromQL query,
   LogQL query, Tempo trace search, dashboard search, alert list, incident
   create. You'll wire these into agent code in Section 5.
4. **Set up a demo application to test against** — you need *something*
   producing metrics/logs/traces into this Grafana stack, or there's nothing
   for the agents to correlate against. Easiest path: deploy a small sample
   app (e.g. a Flask/FastAPI service) instrumented with the OpenTelemetry
   Collector shipping to Grafana Cloud. This becomes "the app under test."
5. **Install ADK** (`pip install google-adk` or the current package name —
   check the ADK docs for the latest install command) and confirm the
   Grafana Cloud MCP integration example from Google's docs runs against
   your stack.
6. **Decide hosted vs self-hosted MCP now, not later:**
   - Hosted `mcp.grafana.com` → fine for building on your laptop and
     recording the demo (you do the one-time browser auth).
   - Self-hosted `grafana/mcp-grafana` with a service-account token → needed
     if you want the "email arrives → pipeline runs automatically, no human
     at a keyboard" story to actually be true. Stand this up in Docker early
     if that's part of your pitch, since it changes your MCP client config.

---

## 4. Repo structure

```
testmind-agentic-iq/
├── README.md                  # hackathon submission readme
├── LICENSE                    # required — open-source license
├── agents/
│   ├── intake_agent.py        # parses release email
│   ├── discovery_agent.py     # extracts what changed / what to test
│   ├── testgen_agent.py       # generates test cases
│   ├── automation_agent.py    # executes tests, calls Grafana MCP
│   ├── self_healing_agent.py  # diagnoses + fixes failures via Grafana MCP
│   └── reporting_agent.py     # writes summary, annotates Grafana
├── orchestrator/
│   └── pipeline.py            # ADK session wiring, Pub/Sub consumer
├── mcp_config/
│   └── grafana_mcp.yaml       # MCP server connection config (hosted/self-hosted)
├── trigger/
│   └── gmail_watcher.py       # Gmail API push listener
├── sample_app/                # small instrumented app under test (optional but recommended)
├── tests_generated/           # output dir for generated test cases
├── evals/                     # your own test cases for the agents, if time allows
└── demo/
    └── script.md              # 3-minute demo video script/shot list
```

---

## 5. Agent-by-agent build plan

For each agent: responsibility, inputs/outputs, and — critically — the
Grafana MCP calls it makes.

### 5.1 Intake agent

- **Input:** raw email (subject, body, attachments) via Gmail API.
- **Output:** structured JSON `{feature_name, description, affected_services, release_id}`.
- **Grafana MCP:** none directly. This agent is pure NLP extraction — an LLM
  call with a structured-output prompt.
- **Build note:** don't over-engineer parsing. A single Gemini/Claude call
  with a JSON schema in the system prompt is enough for a hackathon.

### 5.2 Discovery agent

- **Input:** structured release info from intake agent.
- **Output:** list of "things to verify" — endpoints, user flows, feature
  flags touched.
- **Grafana MCP (optional, nice-to-have):** search dashboards
  (`search_dashboards`-style tool) related to the affected service, to see
  what's normally monitored for it — gives the agent context on what
  "healthy" looks like before tests even run.

### 5.3 TestGen agent

- **Input:** discovery output.
- **Output:** concrete test cases (Playwright scripts or API test specs)
  written to `tests_generated/`.
- **Grafana MCP:** none. Pure generation task.
- **Build note:** keep test cases in a simple JSON/YAML intermediate format
  before rendering to Playwright code — makes the self-healing agent's job
  of patching a single test much easier than regenerating whole scripts.

### 5.4 Automation agent — **primary Grafana MCP consumer**

- **Input:** generated test cases.
- **Output:** pass/fail results + a "telemetry window" (start/end timestamp
  of the test run).
- **Grafana MCP calls:**
  - Query metrics tool (PromQL) for error rate / latency of the affected
    service over the test-run window.
  - Query logs tool (LogQL) for any error-level logs emitted during the run.
  - This is what turns "test failed" into "test failed *and here's the
    production-side evidence of why*" — the core differentiator vs. a plain
    Playwright run.
- **Build note:** log the exact MCP tool name + query + response for every
  call. You'll want these in your demo to prove the connection is live, not
  mocked.

### 5.5 Self-healing agent — **second primary Grafana MCP consumer**

- **Input:** a failed test + its telemetry window from the automation agent.
- **Output:** either a patched test case (if the failure was a selector/API
  contract change) or an escalation flag (if the failure indicates a real
  regression).
- **Grafana MCP calls:**
  - Trace search tool (Tempo) — pull the trace for the failing request to
    see exactly which service/span errored.
  - Alert/incident tools — check if there's already a firing alert for this
    service (if yes, don't try to "heal" the test — the app is actually
    broken; escalate instead).
- **Build note:** this agent's decision logic is your most interesting demo
  moment — "test failed → agent checked Grafana → saw no alert firing → concluded
  it was a stale selector → healed itself" is a great 30-second clip.

### 5.6 Reporting agent

- **Input:** all results from the run.
- **Output:** a written summary + a link back into Grafana.
- **Grafana MCP calls:**
  - Dashboard annotation tool — mark the dashboard at the test-run time with
    pass/fail and a link to the report.
  - (Optional) Incident creation tool if the self-healing agent escalated.
- **Build note:** this is your "Test Manager Dashboard" replacement — instead
  of a custom UiPath dashboard, you're pushing directly into the Grafana
  dashboard the team already watches. That's a stronger story for judges
  than a bespoke UI.

---

## 6. Orchestration flow (runtime)

```
Gmail push notification
        │
        ▼
 intake_agent.py  ──►  publishes task to Pub/Sub topic "release-events"
        │
        ▼
 orchestrator/pipeline.py (ADK session)
   ├─► discovery_agent
   ├─► testgen_agent
   ├─► automation_agent  ──MCP──► Grafana (metrics, logs)
   ├─► self_healing_agent ──MCP──► Grafana (traces, alerts)
   └─► reporting_agent    ──MCP──► Grafana (annotate dashboard)
```

Keep each agent as an independent ADK agent with its own tool bindings
rather than one monolithic prompt — it makes the MCP tool usage visible and
auditable per-agent, which is exactly what you want for both debugging and
the demo.

---

## 7. AI Observability (do this once the pipeline works end-to-end)

Instrument the ADK agents with the Grafana AI Observability SDK
(OpenTelemetry-based) so you can pull up a Grafana dashboard showing your
own agent's LLM calls, token cost, and MCP tool-call latency live during the
demo. This is "recommended, not required" per the partner brief — but it's
a cheap way to visually prove the whole thing is real and running, not
slides.

---

## 8. Suggested build order / rough timeline

| Phase | What                                                         | Goal                                                      |
| ----- | ------------------------------------------------------------ | --------------------------------------------------------- |
| 1     | Grafana account, MCP terms accepted, manual tool exploration | Confirm MCP access works before writing agent code        |
| 2     | Sample app instrumented, shipping telemetry to Grafana       | Something for agents to actually query                    |
| 3     | Intake agent + Gmail trigger                                 | End-to-end trigger works                                  |
| 4     | Discovery + TestGen agents                                   | Test cases get generated from a real email                |
| 5     | Automation agent + first live Grafana MCP metrics/logs call  | **First working Grafana integration — checkpoint** |
| 6     | Self-healing agent + Tempo/alerts calls                      | Core "wow" feature                                        |
| 7     | Reporting agent + dashboard annotation                       | Closes the loop back into Grafana                         |
| 8     | AI Observability instrumentation                             | Optional polish                                           |
| 9     | README, LICENSE, repo cleanup, demo video                    | Submission-ready                                          |

Treat Phase 5 as your first real milestone — once one agent makes one real
call to `mcp.grafana.com` and gets real data back, the hardest integration
risk is retired.

---

## 9. Submission checklist

- [ ] Public GitHub repo
- [ ] Open-source license file (MIT/Apache-2.0 are safe defaults)
- [ ] README explaining the architecture and clearly naming the Grafana MCP
  server as the integration point (judges will look for this explicitly)
- [ ] ~3-minute demo video showing: email arrives → pipeline runs → a visible
  Grafana MCP tool call and response → self-healing decision → dashboard
  annotation appearing in Grafana
- [ ] Confirm the demo either runs against the hosted MCP endpoint (with
  your one-time OAuth already done) or the self-hosted server with a
  service-account token — don't discover an auth gap while recording

---

## 10. Open questions to resolve before you start coding

- Gemini vs Claude as the underlying LLM for each agent (ADK supports both;
  pick one to keep the demo consistent, mix only if there's a clear reason).
- Where does the "app under test" come from — a toy app you build, or an
  existing open-source app you can point tests at? This decides how much of
  Phase 2 you actually need to build.
- Hosted vs self-hosted MCP for the *demo recording itself* — decide this
  early since it affects your `mcp_config/grafana_mcp.yaml` and whether you
  need Docker running during the recording.
