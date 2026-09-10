"""Explicit opt-in live acceptance. --create performs at most the configured research budget."""
import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from backend.app.config import Settings
from backend.app.models import ShotPlan


def main(args):
    settings = Settings()
    secrets = [k.get_secret_value() for k in
               (settings.dashscope_api_key, settings.amap_web_service_key, settings.flickr_api_key)
               if k.get_secret_value()]
    with httpx.Client(base_url=args.url + "/v1", timeout=30, trust_env=False) as client:
        def call(path, body=None):
            response = client.get(path) if body is None else client.post(path, json=body)
            response.raise_for_status()
            if any(secret in response.text for secret in secrets):
                raise ValueError("SECRET_IN_RESPONSE")
            return response.json()
        plan_id = args.plan_id
        if args.create:
            tomorrow = (datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(days=1)).date().isoformat()
            brief = {"destination": "南京玄武湖", "travel_date": tomorrow, "start_local": "14:00", "end_local": "19:00",
                     "intent": {"categories": ["landscape", "architecture"], "subjects": ["紫峰大厦", "城墙"],
                                "styles": ["倒影", "极简"], "light": "daylight"},
                     "lenses": [{"name": "35mm F1.8", "min_mm": 35, "max_mm": 35, "max_aperture": 1.8}],
                     "mode": "live"}
            plan_id = call("/photo-research", brief)["research_id"]
            print(json.dumps({"research_id": plan_id, "status": "started"}), flush=True)
            deadline = time.monotonic() + 200
            while time.monotonic() < deadline:
                job = call(f"/photo-research/{plan_id}")
                if job["status"] in ("complete", "failed"):
                    break
                time.sleep(1)
            if job["status"] != "complete":
                print(json.dumps({"status": job["status"], "events": job.get("events", [])}, ensure_ascii=True))
                return False
        plan = ShotPlan.model_validate(call(f"/plans/{plan_id}"))
        photos = {p.id: p for s in plan.spots for p in s.photo_references}
        image_checks = []
        # Exercise every AMap reference and one reference per optional source, with no paid calls.
        sampled = set()
        for item in photos.values():
            if item.provider != "amap" and item.provider in sampled:
                continue
            sampled.add(item.provider)
            response = client.get(f"/plans/{plan_id}/photos/{item.id}")
            image_checks.append({"id": item.id, "provider": item.provider, "status": response.status_code,
                                 "mime": response.headers.get("content-type"), "bytes": len(response.content)})
        checks = {
            "schema_evidence_integrity": True,
            "live_no_fixtures": plan.brief.mode == "live" and all(e.label != "FIXTURE" for e in plan.evidence),
            "structured_intent": bool(plan.brief.intent and plan.brief.intent.equipment and plan.brief.intent.constraints),
            "nonempty_tasks": bool(plan.tasks),
            "real_reference_metadata": bool(photos),
            "real_image_proxy": any(r["status"] == 200 and r["bytes"] > 100 for r in image_checks),
            "source_claims": any(c.kind == "viewpoint" for c in plan.claims),
            "photo_claims": any(c.kind == "photo" for c in plan.claims),
            "mapped_viewpoint": any(s.viewpoint_status == "mapped_viewpoint" for s in plan.spots),
            "subject_direction": any(t.target_bearing_deg is not None for t in plan.tasks),
            "weather": bool(plan.tasks) and all(t.weather.label == "REPORTED" for t in plan.tasks),
            "solar": plan.solar.sunset is not None,
            "no_false_access": all(s.access == "UNKNOWN" for s in plan.spots),
            "missing_photo_404": client.get(f"/plans/{plan_id}/photos/nonexistent").status_code == 404,
        }
        report = {"checked_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(), "plan_id": plan_id,
                  "passed": all(checks.values()), "checks": checks, "metrics": plan.metrics, "images": image_checks,
                  "capabilities": settings.public_status(), "warnings": plan.warnings,
                  "spots": [{"name": s.name, "place": s.place.name, "status": s.viewpoint_status,
                             "subject": [t.name for t in s.subjects], "photos": len(s.photo_references)} for s in plan.spots]}
        folder = Path(__file__).resolve().parents[1] / "docs/verification"
        folder.mkdir(exist_ok=True)
        for name, content in (("product-upgrade-live.json", report), ("product-upgrade-plan.json", plan.model_dump(mode="json"))):
            encoded = json.dumps(content, ensure_ascii=False, indent=2)
            if any(secret in encoded for secret in secrets):
                raise ValueError("SECRET_IN_ARTIFACT")
            (folder / name).write_text(encoded, encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True), flush=True)
        return report["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--create", action="store_true", help="Explicitly create a real plan; may incur provider charges")
    mode.add_argument("--plan-id")
    parser.add_argument("--url", default="http://127.0.0.1:3800")
    try:
        success = main(parser.parse_args())
    except Exception as error:
        print(json.dumps({"passed": False, "error_type": type(error).__name__}))
        success = False
    raise SystemExit(0 if success else 1)
