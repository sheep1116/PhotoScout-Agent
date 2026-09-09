"""Validate a real UI-generated plan; optional approval exercise affects only that plan."""
import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from backend.app.config import Settings
from backend.app.models import ShotPlan
from backend.app.providers import source_mentions_location


def validate(plan_id, exercise=False):
    settings = Settings()
    checks = {}
    secrets = [s.get_secret_value() for s in (settings.dashscope_api_key, settings.amap_web_service_key)
               if s.get_secret_value()]
    with httpx.Client(base_url="http://127.0.0.1:3800/v1", timeout=60, trust_env=False) as client:
        def call(path, data=None):
            response = client.get(path) if data is None else client.post(path, json=data)
            response.raise_for_status()
            if any(secret in response.text for secret in secrets):
                raise ValueError("SECRET_PRESENT_IN_RESPONSE")
            return response.json()

        plan = ShotPlan.model_validate(call(f"/plans/{plan_id}"))
        checks["live_mode"] = plan.brief.mode == "live"
        checks["nonempty_tasks"] = len(plan.tasks) >= 1
        checks["no_fixture"] = all(e.label != "FIXTURE" for e in plan.evidence)
        checks["real_search_claims"] = bool(plan.claims) and all(
            any(s.id == c.source_id and s.url for s in plan.sources) for c in plan.claims)
        checks["location_relevant_claim_sources"] = bool(plan.claims) and all(any(
            s.id == c.source_id and source_mentions_location(s.title,
                next(spot.name for spot in plan.spots if spot.id == c.subject_id), plan.brief.destination)
            for s in plan.sources) for c in plan.claims)
        checks["no_unreferenced_web_sources"] = all(any(e.source_id == s.id for e in plan.evidence)
            for s in plan.sources if s.id.startswith("web-"))
        checks["map_positions"] = bool(plan.spots) and all(
            any(e.id in s.camera.evidence_ids and e.values.get("provider_id") for e in plan.evidence)
            for s in plan.spots)
        checks["forecast_present"] = bool(plan.tasks) and all(t.weather.label == "REPORTED"
            and t.weather.temperature_c is not None and t.weather.wind_kmh is not None for t in plan.tasks)
        checks["aqi_present"] = bool(plan.tasks) and all(t.weather.aqi is not None for t in plan.tasks)
        checks["no_false_permission"] = all(s.access == "UNKNOWN" for s in plan.spots)
        checks["solar_calculated"] = bool(plan.solar.sunset and plan.solar.golden_start)
        checks["no_unverified_routes"] = not plan.routes if any(s.entrance is None for s in plan.spots) else True
        checks["schema_and_evidence_integrity"] = True  # model_validate above executes integrity validators
        job = call(f"/photo-research/{plan_id}")
        checks["job_complete"] = job["status"] == "complete"
        checks["health_without_secrets"] = call("/health")["status"] == "ok"
        initial = plan.model_dump(mode="json")
        if exercise:
            task = next(t for t in plan.tasks if t.status != "CANCELLED")
            body = {"task_id": task.id, "reason": "Live 验收：用户模拟条件变化", "version": plan.version}
            proposal = call(f"/plans/{plan_id}/proposals", body)
            rejected = call(f"/proposals/{proposal['id']}/decision", {"approve": False, "version": plan.version})
            checks["rejection_preserves_plan"] = rejected == initial
            proposal = call(f"/plans/{plan_id}/proposals", body)
            approved = call(f"/proposals/{proposal['id']}/decision", {"approve": True, "version": plan.version})
            checks["approval_increments_version"] = approved["version"] == plan.version + 1
            checks["only_target_task_changed"] = all(a == b for a, b in zip(initial["tasks"], approved["tasks"])
                                                     if a["id"] != task.id)
            checks["target_cancelled"] = next(t for t in approved["tasks"] if t["id"] == task.id)["status"] == "CANCELLED"
            restored = call(f"/plans/{plan_id}/undo", {"version": approved["version"]})
            expected = {**initial, "version": plan.version + 2}
            checks["undo_restores_content_new_version"] = restored == expected
            plan = ShotPlan.model_validate(restored)
            refresh = call(f"/plans/{plan_id}/refresh", {"version": plan.version})
            checks["fresh_weather_no_unnecessary_proposal"] = refresh["proposal"] is None
        checks["reread_persisted"] = call(f"/plans/{plan_id}") == plan.model_dump(mode="json")
        checks["history_has_current_version"] = any(v["version"] == plan.version
                                                     for v in call(f"/plans/{plan_id}/history"))
    report = {"checked_at": datetime.now(UTC).isoformat(), "plan_id": plan_id, "version": plan.version,
        "destination": plan.brief.destination, "travel_date": plan.brief.travel_date.isoformat(),
        "checks": checks, "passed": all(checks.values()), "metrics": plan.metrics,
        "spot_names": [s.name for s in plan.spots], "task_count": len(plan.tasks),
        "web_source_count": sum(s.id.startswith("web-") for s in plan.sources),
        "claim_count": len(plan.claims), "evidence_count": len(plan.evidence),
        "weather": [{"at": t.weather.at.isoformat(), "temperature_c": t.weather.temperature_c,
                     "wind_kmh": t.weather.wind_kmh, "aqi": t.weather.aqi} for t in plan.tasks],
        "warnings": plan.warnings, "stages": [e["stage"] for e in job.get("events", [])],
        "scope": "Live pipeline acceptance; does not certify source claims, entrances or on-site safety."}
    folder = Path(__file__).resolve().parents[1] / "docs" / "verification"
    folder.mkdir(exist_ok=True)
    for name, data in ((f"live-{plan_id}.json", report), (f"plan-{plan_id}.json", plan.model_dump(mode="json"))):
        encoded = json.dumps(data, ensure_ascii=False, indent=2)
        if any(secret in encoded for secret in secrets):
            raise ValueError("SECRET_PRESENT_IN_ARTIFACT")
        (folder / name).write_text(encoded, encoding="utf-8")
    print(json.dumps({"plan_id": plan_id, "passed": report["passed"], "checks": checks,
                      "metrics": plan.metrics, "task_count": len(plan.tasks)}, ensure_ascii=False))
    return report["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--exercise", action="store_true", help="Approve/reject/undo a test proposal on this plan")
    args = parser.parse_args()
    try:
        success = validate(args.plan_id, args.exercise)
    except Exception as error:
        print(json.dumps({"passed": False, "error_type": type(error).__name__}))
        success = False
    raise SystemExit(0 if success else 1)
