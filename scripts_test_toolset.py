import asyncio

from orchestrator.config import load_config
from orchestrator.deps import build_grafana_toolset


async def main():
    cfg = load_config()
    ts = build_grafana_toolset(cfg)
    try:
        tools = await ts.get_tools_with_prefix(None)
        by_name = {t.name: t for t in tools}
        print("count:", len(tools))
        # 1. Search dashboards
        print("\n== search_dashboards ==")
        search = by_name.get("grafana_search_dashboards")
        if search:
            res = await search.func(query="TestMind")
            print("RESULT:", str(res)[:500])
        # 2. Query Prometheus (no data expected, but proves live call)
        print("\n== query_prometheus ==")
        prom = by_name.get("grafana_query_prometheus")
        if prom:
            try:
                res = await prom.func(
                    from_time="now-15m",
                    to_time="now",
                    query="up",
                )
                print("RESULT:", str(res)[:500])
            except Exception as e:
                print("ERR:", e)
        # 3. user_info to prove auth
        print("\n== user_info ==")
        ui = by_name.get("grafana_user_info")
        if ui:
            try:
                res = await ui.func()
                print("RESULT:", str(res)[:300])
            except Exception as e:
                print("ERR:", e)
    finally:
        await ts.close()


asyncio.run(main())