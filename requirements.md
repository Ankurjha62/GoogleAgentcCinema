# TestMind — Requirements (Pre-Project Checklist)

Everything you need in place **before** writing agent code, derived from
`DevelopmentNotes.md`.

---

## 1. Accounts & Access

| # | Item | Details | Status |
|---|------|---------|--------|
| 1.1 | Grafana Cloud account | Free tier at grafana.com/products/cloud. Creator becomes stack admin (Editor role — required for MCP). | ☐ |
| 1.2 | Grafana Assistant terms accepted | One-time action by stack admin. **Must be done before any MCP tool call works.** | ☐ |
| 1.3 | Google Cloud project | Needed for Gmail API + Pub/Sub (trigger & task coordination). Enable billing if required by Pub/Sub push. | ☐ |
| 1.4 | Gmail API enabled + OAuth credentials | For the email trigger (`gmail_watcher.py`). OAuth consent screen configured for test users. | ☐ |
| 1.5 | Pub/Sub topic + subscription | `release-events` topic; push subscription to trigger the pipeline. | ☐ |
| 1.6 | LLM API key(s) | Gemini (Google AI Studio) and/or Anthropic API key — pick one primary per Open Question 10.1. | ☐ |
| 1.7 | Grafana service account + token | Required only if self-hosting MCP (`grafana/mcp-grafana`) for headless/automated runs. | ☐ |
| 1.8 | Public GitHub repo | Hackathon submission requirement. | ☐ |

---

## 2. Software & Tools (local machine)

| # | Item | Notes |
|---|------|-------|
| 2.1 | Python 3.10+ | Runtime for ADK, Playwright, agents. |
| 2.2 | Google ADK installed (`pip install google-adk`) | Verify exact package name against current ADK docs. |
| 2.3 | Docker Desktop | Only if self-hosted MCP is chosen — needed early since it changes MCP client config. |
| 2.4 | Playwright + browsers (`playwright install`) | UI test execution engine. |
| 2.5 | Gemini CLI or Claude Desktop | For **manual exploration** of the 60+ Grafana MCP tools (Phase 1). |
| 2.6 | Git | Repo management. |
| 2.7 | OTel Collector (optional) | To ship sample-app telemetry to Grafana Cloud. |

---

## 3. Credentials / Secrets to Collect

Store in `.env` (gitignored) or a secrets manager:

- [ ] `GRAFANA_URL` — `https://<your-stack>.grafana.net`
- [ ] `MCP_ENDPOINT` — `https://mcp.grafana.com/mcp` (hosted) or self-hosted URL
- [ ] `GRAFANA_SERVICE_ACCOUNT_TOKEN` — self-hosted path only
- [ ] `GEMINI_API_KEY` / `ANTHROPIC_API_KEY`
- [ ] `GCP_PROJECT_ID`, Gmail OAuth client secret JSON, Pub/Sub subscription name
- [ ] Sample app → Grafana: OTLP endpoint + Grafana Cloud token (metrics/logs/traces)

---

## 4. Key Decisions (resolve before coding)

- [ ] **LLM choice:** Gemini vs Claude as the single primary model (Open Q 10.1).
- [ ] **MCP mode:** Hosted `mcp.grafana.com` (one-time browser OAuth, fine for laptop/demo) vs self-hosted with service-account token (needed for a truly hands-free "email → run" story). Affects `mcp_config/grafana_mcp.yaml`.
- [ ] **App under test:** build a small instrumented Flask/FastAPI sample app vs point tests at an existing open-source app. Determines scope of Phase 2.
- [ ] **Storage:** Firestore vs simple Postgres for test-case store + run history.
- [ ] **Trigger mechanism:** Gmail API push via Pub/Sub vs IMAP polling.

---

## 5. Milestone Gate (Phase 5 = first hard checkpoint)

Before building agents beyond the first one, prove:

- [ ] One agent makes **one real call** to the Grafana MCP endpoint and gets real data back.
- [ ] Exact tool names noted from manual exploration: PromQL query, LogQL query, Tempo trace search, dashboard search, alert list, incident create, annotation add.

---

## 6. Submission Deliverables

- [ ] Public repo with README naming **Grafana Cloud MCP server** explicitly as the integration
- [ ] LICENSE file (MIT or Apache-2.0)
- [ ] ~3-min demo video: email arrives → pipeline runs → visible MCP call/response → self-heal decision → dashboard annotation appears
- [ ] Auth path verified *before* recording (hosted OAuth done, or service-account token working)

---

## 7. Python Dependencies (initial)

```
google-adk          # agent framework (confirm current name)
playwright          # UI test execution
httpx               # API test execution
google-api-python-client, google-auth-oauthlib   # Gmail
google-cloud-pubsub # task coordination
opentelemetry-sdk, opentelemetry-exporter-otlp  # sample app instrumentation
python-dotenv       # secrets loading
pydantic            # structured outputs between agents
```

*(Pin versions after first successful install; verify each against current docs.)*
