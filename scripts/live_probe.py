"""Opt-in real service probes. Never print raw responses, URLs with keys, or exceptions."""
import argparse
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.app.config import Settings
from backend.app.engine import Ledger
from backend.app.models import Position, TripBrief
from backend.app.providers import ProviderError, Providers, gcj_to_wgs


async def probe(paid_search=False):
    settings = Settings()
    provider = Providers(settings)
    report = {"at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(), "checks": {}}
    brief = TripBrief(destination="南京", travel_date=(datetime.now(ZoneInfo("Asia/Shanghai"))
        + timedelta(days=1)).date(), start_local="14:00", end_local="19:00", genre="portrait", mode="live")

    def safe_json(value, indent=None):
        encoded = json.dumps(value, ensure_ascii=False, indent=indent)
        for secret in (settings.dashscope_api_key, settings.amap_web_service_key):
            if secret.get_secret_value():
                encoded = encoded.replace(secret.get_secret_value(), "[REDACTED]")
        return encoded

    async def check(name, action):
        try:
            result = await action()
            report["checks"][name] = result
        except ProviderError as error:
            report["checks"][name] = {"ok": False, "provider": error.provider, "code": error.code}
        except Exception as error:
            report["checks"][name] = {"ok": False, "error_type": type(error).__name__}
        print(safe_json({name: report["checks"][name]}), flush=True)

    async def amap():
        geo = await provider.geocode("南京市")
        poi = await provider.poi("玄武湖景区", "南京市")
        return {"ok": True, "city": geo.get("city"), "poi_id": poi.get("id"), "poi_name": poi.get("name"),
                "position_wgs84": gcj_to_wgs(*map(float, poi["location"].split(",")))}

    async def weather():
        ledger = Ledger()
        rows = await provider.weather(brief, Position(lat=32.07, lon=118.8, evidence_ids=["probe"]), ledger)
        return {"ok": any(r.temperature_c is not None and r.label == "REPORTED" for r in rows),
                "hour_count": len(rows), "aqi_hours": sum(r.aqi is not None for r in rows),
                "date": brief.travel_date.isoformat(), "labels": sorted({r.label for r in rows}),
                "notes": [e.statement for e in ledger.evidence if e.label == "UNKNOWN"]}

    async def search():
        data = await provider.search(brief, "社区摄影攻略 新机位 构图经验")
        return {"ok": bool(data["sources"] and data["candidates"]), "source_count": len(data["sources"]),
                "source_titles": [s.get("title") for s in data["sources"]],
                "candidate_names": [c["name"] for c in data["candidates"]], "reported_tokens": provider.tokens}

    try:
        await asyncio.gather(check("amap", amap), check("weather", weather))
        if paid_search:
            await check("dashscope", search)
    finally:
        await provider.client.aclose()
    report["provider_calls"] = provider.calls
    folder = Path(__file__).resolve().parents[1] / ".run"
    folder.mkdir(exist_ok=True)
    encoded = safe_json(report, indent=2)
    (folder / "live-probe.json").write_text(encoded, encoding="utf-8")
    return all(check["ok"] for check in report["checks"].values())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--paid-search", action="store_true", help="Explicitly permit one billed search request")
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(probe(args.paid_search)) else 1)
