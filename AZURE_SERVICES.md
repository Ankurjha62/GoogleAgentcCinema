# TestMind — Azure Services Reference

This document maps every TestMind component to the Azure service(s) best suited
for production-grade implementation. Use it as a blueprint when moving from the
hackathon demo to a real deployment.

---

## Quick Mapping Table

| TestMind Component | Azure Service(s) | Purpose |
|---|---|---|
| Agent orchestration pipeline | Azure Container Apps | Run the 6-agent Python pipeline as containers |
| Email trigger (Gmail IMAP) | Azure Logic Apps + Event Grid | Serverless email watcher, no IMAP polling |
| Sample app (FastAPI) | Azure App Service | Host the e-commerce app under test |
| LLM / AI agents | Azure AI Foundry (OpenAI GPT-4o or Gemini via Azure) | Replace or supplement local Gemini calls |
| Test case & test plan management | Azure DevOps Test Plans | Author, version, and track test cases/plans |
| Test execution tracking | Azure DevOps Work Items (Boards) | Log pass/fail status, link to pipeline runs |
| CI/CD pipeline | Azure DevOps Pipelines | Build, test, deploy on every commit/PR |
| Artifact storage (JSON reports, test specs) | Azure Blob Storage | Persistent, versioned storage for run artifacts |
| Database (structured data) | Azure Cosmos DB | Store release info, test results, heal decisions |
| Observability (metrics, logs, traces) | Azure Monitor + Application Insights | Replace Grafana Cloud with native Azure telemetry |
| Dashboards & annotations | Azure Managed Grafana | Native Azure Grafana, managed and linked to Monitor |
| Secrets management | Azure Key Vault | Gemini API keys, service tokens, DB connection strings |
| Alerts & incident response | Azure Monitor Alerts + Azure DevOps | Alert rules → work items auto-created on failures |
| Self-healing decision logging | Azure Cosmos DB + Azure Logic Apps | Store heal decisions, notify via Teams/email |
| Reports (Markdown) | Azure Blob Storage + Power BI (optional) | Store reports, optionally visualize in dashboards |
| MCP server hosting | Azure Container Apps (sidecar) | Run Grafana MCP server as a sidecar container |

---

## Detailed Breakdown by Task

### 1. Agent Pipeline Orchestration

**Azure Service: Azure Container Apps**

- Package each agent (or the full pipeline) as a Docker container
- Use Azure Container Apps Jobs for the sequential pipeline execution
- Event-driven trigger: Logic App sends a message to Azure Service Bus →
  Container App Job picks it up and runs the 6-stage pipeline
- Auto-scales to zero when idle (cost-efficient for event-driven workloads)
- Environment variables injected from Key Vault (no `.env` files in prod)

**Why not Azure Functions?** Functions have a 10-minute execution limit; the
full 6-agent pipeline with LLM calls and retries can exceed that. Container
Apps have no hard time limit.

---

### 2. Email Trigger

**Azure Service: Azure Logic Apps ( Consumption plan )**

- Built-in Gmail connector (no IMAP polling code needed)
- Trigger: "When a new email arrives" with filter on subject/body keywords
- Actions: Extract subject + body → push message to Service Bus topic →
  Container App Job is triggered via Service Bus binding
- Handles retries, duplicate detection, and dead-letter queue natively
- Replaces `trigger/gmail_watcher.py` entirely

**Alternative: Azure Event Grid + Microsoft Graph API** for Exchange/Outlook
emails if migrating away from Gmail.

---

### 3. Test Case & Test Plan Management

**Azure Service: Azure DevOps Test Plans**

| What | Where in Azure DevOps |
|---|---|
| Test cases (individual) | Test Plans → Test Suites → Test Cases |
| Test plans (suites grouped by feature/release) | Test Plans → Test Plans |
| Shared steps (reusable steps across test cases) | Test Plans → Shared Steps |
| Test configurations (browsers, OS, environments) | Test Plans → Configurations |
| Traceability to requirements | Link test cases → Work Items (User Stories/Bugs) |
| Execution history | Test Plans → Runs & Results |

**Integration with TestMind pipeline:**

- **TestGen Agent** outputs JSON test specs → a custom script calls the
  Azure DevOps REST API to create/update Test Cases automatically
- **Automation Agent** results are pushed back as Test Run results via the API
- **Self-Healing Agent** updates the Test Case definition when it patches a
  spec (so the "fixed" version is the source of truth in ADO)

**Key APIs:**
```
POST   /testplan/{planId}/testcase          — create test case
PATCH  /testplan/{planId}/testcase/{caseId} — update (self-heal)
POST   /testplan/{planId}/testrun           — create test run
POST   /testplan/{planId}/testrun/{runId}/results — publish results
```

---

### 4. CI/CD Pipeline

**Azure Service: Azure DevOps Pipelines (YAML)**

```yaml
# Trigger: on push to main or PR
trigger:
  branches:
    include: [main]

stages:
  - stage: Build
    jobs:
      - job: BuildAndTest
        pool:
          vmImage: 'ubuntu-latest'
        steps:
          - task: UsePythonVersion@0
            inputs:
              versionSpec: '3.13'
          - script: pip install -r requirements.txt
          - script: python -m pytest tests/ --junitxml=test-results.xml
          - task: PublishTestResults@2
          - task: PublishBuildArtifacts@1

  - stage: DeploySampleApp
    dependsOn: Build
    jobs:
      - deployment: DeployApp
        environment: 'staging'
        strategy:
          runOnce:
            deploy:
              steps:
                - task: AzureWebAppContainer@1
                  inputs:
                    azureSubscription: 'testmind-service-connection'
                    appName: 'testmind-sample-app'

  - stage: RunPipeline
    dependsOn: DeploySampleApp
    jobs:
      - job: AgenticRun
        steps:
          - task: AzureCLI@2
            inputs:
              azureSubscription: 'testmind-service-connection'
              scriptType: 'bash'
              scriptLocation: 'inlineScript'
              inlineScript: |
                az containerapp job start \
                  --name testmind-pipeline \
                  --resource-group testmind-rg
```

**PR validation:** Pipeline runs the full agent pipeline against the staging
environment on every PR. Pass/fail status is posted back to the PR as a check.

---

### 5. LLM / AI Agents

**Azure Service: Azure AI Foundry (Azure OpenAI Service)**

Replace the local Gemini calls with Azure-hosted models:

| Current (Gemini) | Azure Equivalent | When to Use |
|---|---|---|
| `gemini-3.5-flash-lite` | GPT-4o-mini | Fast, cheap — good for Intake/TestGen agents |
| `gemini-2.5-pro` (if upgraded) | GPT-4o | Complex reasoning — Self-Healing agent |
| — | Azure AI Agent Service | Managed agent runtime with tool use |

**Why Azure OpenAI over raw Gemini?**
- Data stays in your Azure tenant (no data sent to Google)
- Azure RBAC for access control
- Integrated with Azure Monitor for token usage tracking
- SLA-backed availability
- Easy to swap models per agent without changing infrastructure

**Configuration:**
```python
# orchestrator/config.py addition
AZURE_OPENAI_ENDPOINT = "https://testmind-openai.openai.azure.com/"
AZURE_OPENAI_API_KEY  = from Key Vault
AZURE_OPENAI_DEPLOYMENT = "gpt-4o-mini"  # per-agent override possible
```

---

### 6. Artifact & Report Storage

**Azure Service: Azure Blob Storage**

| Container | Contents | Lifecycle |
|---|---|---|
| `release-info` | `1_release.json` per run | Archive after 90 days |
| `discovery` | `2_discovery.json` per run | Archive after 90 days |
| `test-specs` | `3_testgen.json`, `tests_generated/*.json` | Retain 1 year |
| `test-results` | `4_automation.json`, `run_*.json` | Retain 1 year |
| `heal-decisions` | `5_selfheal.json` | Retain forever (audit) |
| `reports` | `6_report.md` per run | Retain forever |

- Replace local `storage/` directory with Azure Blob Storage SDK calls
- Use blob metadata to tag runs (pipeline run ID, commit SHA, release version)
- Enable soft delete for accidental overwrite recovery
- Use Azure CDN if reports need public/dashboards access

---

### 7. Structured Data Store

**Azure Service: Azure Cosmos DB (Serverless)**

Store pipeline metadata and structured results that need querying:

| Container | Partition Key | Contents |
|---|---|---|
| `runs` | `/runId` | Full pipeline run metadata, status, timestamps |
| `test-results` | `/runId` | Individual test pass/fail with telemetry windows |
| `heal-decisions` | `/runId` | Self-healing decisions, patches applied |
| `releases` | `/releaseId` | Parsed release info from intake agent |

**Why Cosmos DB?**
- Free tier (1000 RU/s, 25 GB) is enough for a small team
- Serverless mode = zero cost when idle
- Change feed enables real-time dashboards and alerts
- Native integration with Azure Functions and Logic Apps

---

### 8. Observability (Metrics, Logs, Traces)

**Azure Service: Azure Monitor + Application Insights**

Replace the Grafana Cloud stack (Mimir, Loki, Tempo) with native Azure
observability:

| Current (Grafana Cloud) | Azure Equivalent | Mapping |
|---|---|---|
| Mimir (Prometheus metrics) | Azure Monitor Metrics | Container App resource metrics + custom metrics |
| Loki (logs) | Log Analytics Workspace | Container App logs → Log Analytics |
| Tempo (distributed traces) | Application Insights (distributed tracing) | Auto-instrumented by Container Apps |
| OnCall (alerting) | Azure Monitor Alerts | Metric alerts → Action Groups → email/Teams/ADO |

**Self-healing agent integration:**
- The Self-Healing agent currently queries Prometheus/Loki/Tempo via MCP
- In Azure: query Log Analytics (KQL) and Application Insights (Trace)
  instead of PromQL/LogQL
- Same intelligence, different query language

---

### 9. Managed Grafana (Dashboards)

**Azure Service: Azure Managed Grafana**

- Native Azure service — no separate Grafana Cloud account needed
- Automatically connected to Azure Monitor as a data source
- Dashboard annotations from Reporting Agent → Grafana API (same as today)
- Team-level access via Azure AD (no separate Grafana auth)
- Share dashboards with stakeholders via Azure RBAC

---

### 10. Secrets Management

**Azure Service: Azure Key Vault**

| Secret | Purpose |
|---|---|
| `GEMINI-API-KEY` or `AZURE-OPENAI-KEY` | LLM API authentication |
| `GRAFANA-SERVICE-ACCOUNT-TOKEN` | Grafana MCP server auth |
| `GRAFANA-URL` | Grafana stack endpoint |
| `GMAIL-APP-PASSWORD` | Email trigger auth |
| `COSMOS-DB-CONNECTION-STRING` | Database access |
| `ADO-PAT` | Azure DevOps personal access token for REST API |

- Container Apps reference Key Vault via secret references (no env vars in code)
- Managed Identity for service-to-service auth (no secrets for ADO pipelines)
- Automatic rotation support for database connection strings

---

### 11. Alerts & Incident Response

**Azure Service: Azure Monitor Alerts + Azure DevOps Integration**

Configure alerts that feed back into the test management loop:

| Alert Rule | Condition | Action |
|---|---|---|
| Pipeline failure | Container App Job fails | Create Bug work item in ADO |
| High error rate | Sample app HTTP 5xx > 5% | Create Bug + notify Teams |
| Test regression | Test run pass rate drops | Create Bug linked to test plan |
| Self-healing escalation | Heal agent flags "real regression" | Create Bug with Grafana link |

**Action Groups:**
- Email notification to QA team
- Microsoft Teams webhook for real-time visibility
- Azure DevOps webhook to auto-create Bugs

---

### 12. Sample App Hosting

**Azure Service: Azure App Service (Linux)**

- FastAPI app runs as a container or native Python app
- Staging slot for pre-production testing
- Auto-deploy from Azure DevOps pipeline
- Built-in integration with Application Insights for request tracing
- CORS, auth, and custom domains configured via Azure portal

---

## Cost Estimate (Hackathon / Small Team Tier)

| Service | Tier | Estimated Monthly Cost |
|---|---|---|
| Azure Container Apps | Consumption (pay-per-execution) | $5–20 |
| Azure Logic Apps | Consumption | $2–10 |
| Azure App Service | B1 (Basic) | ~$13 |
| Azure OpenAI (GPT-4o-mini) | Pay-as-you-go | $10–50 (depends on volume) |
| Azure Cosmos DB | Serverless | $0–5 (free tier covers small usage) |
| Azure Blob Storage | Hot tier, <1 GB | <$1 |
| Azure Monitor + App Insights | Pay-as-you-go | $5–15 |
| Azure Managed Grafana | Standard | ~$100 (or use free trial) |
| Azure Key Vault | Standard | <$1 |
| Azure DevOps | Free for ≤5 users | $0 |
| **Total (conservative)** | | **~$140–215/mo** |

> For hackathon/demo: Many services have free tiers or $200 initial credit.
> The $0 option is to use Azure DevOps free tier + free Cosmos DB tier
> + Azure Functions Consumption (1M free executions).

---

## Migration Priority (Suggested Order)

| Phase | Services to Add | Effort |
|---|---|---|
| **Phase 1: Foundation** | Key Vault, Blob Storage, DevOps Pipelines | 1–2 days |
| **Phase 2: Test Management** | Azure DevOps Test Plans, Work Item integration | 1–2 days |
| **Phase 3: Hosted Infra** | Container Apps, App Service, Logic Apps | 2–3 days |
| **Phase 4: Observability** | Application Insights, Log Analytics, Managed Grafana | 2–3 days |
| **Phase 5: AI Migration** | Azure OpenAI (replace Gemini calls) | 1–2 days |
| **Phase 6: Advanced** | Cosmos DB, Monitor Alerts, auto-create Bugs | 2–3 days |

---

## Azure CLI Quick-Start Commands

```bash
# Create resource group
az group create --name testmind-rg --location eastus

# Create Key Vault
az keyvault create --name testmind-kv --resource-group testmind-rg

# Create Storage Account + Blob container
az storage account create --name testmindstorage --resource-group testmind-rg
az storage container create --name reports --account-name testmindstorage

# Create Cosmos DB (serverless)
az cosmosdb create --name testmind-db --resource-group testmind-rg --kind GlobalDocumentDB

# Create Container Apps environment
az containerapp env create --name testmind-env --resource-group testmind-rg

# Create App Service Plan + Web App for sample app
az appservice plan create --name testmind-plan --resource-group testmind-rg --sku B1
az webapp create --plan testmind-plan --name testmind-sample-app --resource-group testmind-rg

# Create Logic App for email trigger
az logic workflow create --name testmind-email-trigger --resource-group testmind-rg
```

---

## Useful Links

- [Azure DevOps Test Plans docs](https://learn.microsoft.com/en-us/azure/devops/test/)
- [Azure Container Apps docs](https://learn.microsoft.com/en-us/azure/container-apps/)
- [Azure OpenAI Service docs](https://learn.microsoft.com/en-us/azure/ai-services/openai/)
- [Azure Managed Grafana docs](https://learn.microsoft.com/en-us/azure/managed-grafana/)
- [Azure Cosmos DB free tier](https://learn.microsoft.com/en-us/azure/cosmos-db/free-tier)
