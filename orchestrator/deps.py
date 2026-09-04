"""Shared pipeline context: one Grafana MCP toolset reused by all agents.

The build plan calls for each agent to keep its *own* MCP tool bindings so the
Grafana calls are visible and auditable per agent. We therefore create one
``McpToolset`` (one connection to the OSS mcp-grafana stdio server) and share
it across the agents that need it, rather than opening a new process per agent.
"""
from __future__ import annotations

import os
from typing import Optional

from google.adk.tools.mcp_tool import McpToolset
from mcp import StdioServerParameters

from orchestrator.config import Config

# Tool names the agents rely on. The server behind a Grafana Cloud stack
# (proxied MCP) exposes the "cloud" naming; the OSS server uses a different
# set. We allowlist both so the same config works either way - any name the
# connected server does not provide is simply ignored.
GRAFANA_TOOLS = [
    # metrics (PromQL)
    "query_prometheus",
    "query_prometheus_histogram",
    "metrics_service_query_range",
    # logs (LogQL)
    "query_loki_logs",
    "query_loki_stats",
    "logs_service_query_range",
    "find_error_pattern_logs",
    # traces (Tempo / TraceQL)
    "tempo_traceql-search",
    "tempo_traceql-metrics-range",
    "tempo_get-trace",
    "tempo_service_search_traces",
    # dashboards / annotations
    "search_dashboards",
    "get_dashboard_by_uid",
    "get_dashboard_summary",
    "dashboard_search_dashboards",
    "create_annotation",
    "dashboard_annotations_create",
    # alerts / incidents
    "list_alert_groups",
    "get_alert_group",
    "alertmanager_v1_list_alerts",
    "list_incidents",
    "get_incident",
    "create_incident",
    "incident_create",
    # datasources / helpers
    "list_datasources",
    "check_datasources_health",
    "user_info",
    "generate_deeplink",
]


def build_grafana_toolset(
    cfg: Config,
    tool_filters: Optional[list[str]] = None,
    name_prefix: str = "grafana",
) -> McpToolset:
    """Build an ADK 2.x ``McpToolset`` pointing at the OSS mcp-grafana server.

    Uses the stdio transport (``uv tool run mcp-grafana``) and injects Grafana
    credentials into the server process env so *it* can authenticate to our
    Grafana Cloud stack with a service account token (headless friendly).
    """
    command = os.getenv("MCP_GRAFANA_CMD", "uv")
    if command == "uv":
        args = ["tool", "run", "mcp-grafana"]
    else:
        args = ["run", "--rm", "-i", "grafana/mcp-grafana"]

    env = {
        "GRAFANA_URL": cfg.grafana_url,
        "GRAFANA_SERVICE_ACCOUNT_TOKEN": cfg.grafana_service_account_token,
        "GRAFANA_LOG_LEVEL": os.getenv("GRAFANA_LOG_LEVEL", "warn"),
    }

    selected = (
        GRAFANA_TOOLS if tool_filters is None else tool_filters
    )
    return McpToolset(
        connection_params=StdioServerParameters(
            command=command,
            args=args,
            env=env,
        ),
        tool_filter=selected or None,
        tool_name_prefix=name_prefix,
        tool_list_cache_ttl_seconds=60.0,
    )