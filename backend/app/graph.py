import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .engine import RULE_VERSION, Ledger, notebook
from .fixtures import seed_conditions, seed_spots
from .models import ShotPlan
from .providers import ProviderError, Providers
from .recommendations import build_recommendations
from .verification import popularity, resolve_access


class State(TypedDict, total=False):
    plan_id: str
    brief: Any
    ledger: Any
    spots: list
    claims: list
    conditions: dict
    routes: list
    warnings: list
    plan: Any


async def run_graph(plan_id, brief, settings, emit, provider=None):
    brief = notebook(brief).brief
    started = time.monotonic()
    ledger = Ledger()
    providers = provider or Providers(settings)

    async def parse(state):
        parsed = notebook(state["brief"])
        if parsed.missing_fields:
            raise ValueError("请先确认 Notebook 中的必填信息")
        await emit("parse", "已确认目的地、日期、题材与器材")
        return {"brief": parsed.brief}

    async def discover(state):
        await emit("discover", "正在发现候选与来源" if brief.mode == "live" else "正在读取离线机位 Fixture")
        warnings = []
        if brief.mode == "mock":
            if "南京" not in brief.destination:
                raise ValueError("离线 Demo 仅包含南京；其他目的地请使用 Live 模式")
            spots, claims = seed_spots(brief, ledger)
        else:
            spots, claims = await providers.discover(brief, ledger, warnings)
            if not spots:
                for warning in warnings:
                    await emit("warning", warning)
                raise ProviderError("Discovery", "NO_VERIFIABLE_CANDIDATES")
        await emit("evidence", f"已保留 {len(spots)} 个候选、{len(claims)} 条来源线索；开放仍需复核")
        return {"spots": spots, "claims": claims, "warnings": warnings}

    async def conditions(state):
        await emit("conditions", "正在逐机位整合天气与光线；不安排访问顺序")
        by_spot = {}
        dates = [brief.travel_date]
        if brief.end_date and brief.end_date != brief.travel_date:
            dates.append(brief.end_date)
        for spot in state["spots"]:
            by_spot[spot.id] = []
            for day in dates:
                dated = brief.model_copy(update={"travel_date": day})
                weather = seed_conditions(dated, ledger) if brief.mode == "mock" else await providers.weather(dated, spot.camera, ledger)
                by_spot[spot.id].extend(weather)
        return {"conditions": by_spot, "routes": []}

    async def verify(state):
        from datetime import UTC, datetime
        current = datetime.now(UTC)
        for spot in state["spots"]:
            associated = [c for c in state["claims"] if c.subject_id == spot.id]
            spot.popularity = popularity(associated, ledger.sources, current)
            spot.access = resolve_access(associated, ledger.sources, current)
        await emit("verify", "已分离社区构图与官方权限；缺少有效官方证据的开放状态保留未知")
        return {"spots": state["spots"]}

    async def schedule(state):
        await emit("schedule", "正在独立评估每个机位的窗口、镜头与推荐理由")
        plan = build_recommendations(plan_id, brief, state["spots"], state["claims"], state["conditions"],
                          ledger, state["warnings"])
        return {"plan": plan}

    async def validate(state):
        plan = ShotPlan.model_validate(state["plan"].model_dump())
        plan.metrics = {"elapsed_ms": round((time.monotonic()-started)*1000), "provider_calls": providers.calls,
                        "search_calls": providers.search_calls, "search_cache_hits": providers.search_cache_hits,
                        "reported_tokens": providers.tokens, "cost_cny": None,
                        "cost_note": "未取得计费账单；不估算虚假费用", "rule_version": RULE_VERSION,
                        "photo_references": sum(len(s.photo_references) for s in plan.spots),
                        "mapped_viewpoints": sum(s.viewpoint_status == "mapped_viewpoint" for s in plan.spots),
                        "community": getattr(getattr(providers, "community", None), "status", {}),
                        "photo_providers": sorted({p.provider for s in plan.spots for p in s.photo_references})}
        await emit("validate", "Schema、证据引用和独立候选窗口校验通过")
        return {"plan": plan}

    graph = StateGraph(State)
    nodes = {"parse": parse, "discover": discover, "verify": verify, "conditions": conditions, "schedule": schedule, "validate": validate}
    previous = START
    for name, func in nodes.items():
        graph.add_node(name, func)
        graph.add_edge(previous, name)
        previous = name
    graph.add_edge(previous, END)
    try:
        result = await graph.compile().ainvoke({"plan_id": plan_id, "brief": brief}, {"recursion_limit": 8})
        return result["plan"]
    finally:
        if provider is None:
            await providers.client.aclose()
