"""Coordinate confirmation and condition refresh are proposals, never implicit writes."""
from datetime import UTC, datetime
from uuid import uuid4

from .engine import Ledger, gate
from .models import Evidence, PlanChangeProposal, Position, ShotPlan, TruthLabel, WebSource
from .proposals import field_diff


def position_proposal(plan, spot_id, lat, lon, role):
    changed = plan.model_copy(deep=True)
    spot = next((s for s in changed.spots if s.id == spot_id), None)
    if spot is None:
        raise KeyError(spot_id)
    # Restrict accidental dragging/typing to the known locality.
    if abs(lat - spot.camera.lat) > .05 or abs(lon - spot.camera.lon) > .05:
        raise ValueError("坐标须位于候选周边约 5 公里内；其他地点请重新发现")
    eid = "ev-position-" + uuid4().hex[:12]
    source = WebSource(id="src-" + eid, title="用户地图确认", publisher="本地用户", kind="user")
    changed.sources.append(source)
    changed.evidence.append(Evidence(id=eid, source_id=source.id, label=TruthLabel.USER_CONFIRMED,
        statement="用户记录的公开区域站位/入口；位置确认不代表开放、合法性或安全核验。",
        values={"lat": lat, "lon": lon, "role": role, "crs": "WGS84"}))
    point = Position(lat=lat, lon=lon, precision="MAP_POINT", evidence_ids=[eid])
    if role == "entrance":
        spot.entrance = point
    else:
        spot.camera = point
    # Geometry depends on camera: invalidate instead of keeping stale bearings.
    if role == "camera":
        from astral import Observer
        from astral.sun import azimuth

        from .engine import bearing
        from .recommendations import circular_span, distance_km
        for task in changed.tasks:
            if task.spot_id != spot_id:
                continue
            task.subject_bearings_deg = {subject.name: bearing(point, subject.position)
                                         for subject in spot.subjects if subject.position}
            task.subject_distances_km = {subject.name: distance_km(
                point.lat, point.lon, subject.position.lat, subject.position.lon)
                for subject in spot.subjects if subject.position}
            task.target_bearing_deg = next(iter(task.subject_bearings_deg.values()), None)
            task.subject_separation_deg = circular_span(list(task.subject_bearings_deg.values()))
            if task.subject_separation_deg is None:
                task.framing_assessment = "缺少至少两个可定位主体，暂不能核验同框范围。"
            elif task.field_of_view_deg and task.subject_separation_deg <= task.field_of_view_deg:
                task.framing_assessment = f"两主体方位跨度约 {task.subject_separation_deg}°，平面几何上可纳入当前焦段视角；遮挡仍待现场确认。"
            else:
                task.framing_assessment = f"两主体方位跨度约 {task.subject_separation_deg}°，建议缩短焦段或调整站位。"
            task.solar_azimuth_deg = round(azimuth(Observer(lat, lon), task.start), 1)
            task.evidence_ids.append(eid)
            changed.evidence[-1].values[task.id] = {"solar_azimuth_deg": task.solar_azimuth_deg,
                                                   "target_bearing_deg": task.target_bearing_deg,
                                                   "subject_bearings_deg": task.subject_bearings_deg,
                                                   "subject_distances_km": task.subject_distances_km,
                                                   "subject_separation_deg": task.subject_separation_deg}
    reason = "确认相机站位" if role == "camera" else "确认公开入口"
    return PlanChangeProposal(id=uuid4().hex, plan_id=plan.id, base_version=plan.version, reason=reason,
        proposed=ShotPlan.model_validate(changed.model_dump()),
        diff=field_diff(plan.model_dump(mode="json"), changed.model_dump(mode="json")))


async def refresh_proposal(plan, providers):
    if plan.brief.mode != "live":
        return None
    current = datetime.now(UTC)
    weather_ids = {eid for t in plan.tasks for eid in t.weather.evidence_ids}
    records = [e for e in plan.evidence if e.id in weather_ids and e.valid_until]
    if records and all(e.valid_until > current for e in records):
        return None
    ledger = Ledger()
    from zoneinfo import ZoneInfo
    by_task = {}
    for task in plan.tasks:
        spot = next(s for s in plan.spots if s.id == task.spot_id)
        day = task.start.astimezone(ZoneInfo(plan.brief.timezone)).date()
        dated = plan.brief.model_copy(update={"travel_date": day})
        by_task[task.id] = await providers.weather(dated, spot.camera, ledger)
    if all(w.label == TruthLabel.UNKNOWN for conditions in by_task.values() for w in conditions):
        raise ValueError("天气刷新不可用，已保留原计划与原数据时间戳")
    changed = plan.model_copy(deep=True)
    suffix = uuid4().hex[:8]
    # Refresh snapshots get new evidence IDs and retain the original snapshots.
    mapping = {e.id: e.id + "-" + suffix for e in ledger.evidence}
    for e in ledger.evidence:
        e.id = mapping[e.id]
        e.source_id += "-" + suffix
    for s in ledger.sources:
        s.id += "-" + suffix
    material = False
    for task in changed.tasks:
        if task.status == "CANCELLED":
            continue
        weather = min(by_task[task.id], key=lambda w: abs((w.at-task.start).total_seconds())).model_copy(deep=True)
        old = task.weather
        differs = any(a is None and b is not None or a is not None and b is None or
            (a is not None and b is not None and abs(a-b) >= delta) for a, b, delta in [
                (old.precipitation_mm, weather.precipitation_mm, 1), (old.wind_kmh, weather.wind_kmh, 8),
                (old.temperature_c, weather.temperature_c, 4), (old.visibility_m, weather.visibility_m, 3000)])
        spot = next(s for s in plan.spots if s.id == task.spot_id)
        from .recommendations import candidate_gate
        guard = candidate_gate if plan.presentation == "candidates" else gate
        reason = guard(spot, weather, plan.brief, task.start, task.end)
        if not differs and not reason:
            continue
        material = True
        weather.evidence_ids = [mapping[eid] for eid in weather.evidence_ids]
        task.weather = weather
        if reason:
            task.status = "CANCELLED"
            task.risks.append("条件刷新：" + reason)
        else:
            task.status = "TENTATIVE"
            task.risks.append("天气发生材料变化，请重新检查曝光与现场条件。")
        # Scores depend on conditions; recompute, with refreshed evidence.
        from .engine import solar_windows
        from .recommendations import candidate_score
        score_ledger = Ledger()
        local_day = task.start.astimezone(ZoneInfo(plan.brief.timezone)).date()
        solar = solar_windows(plan.brief.model_copy(update={"travel_date": local_day}), spot.camera, Ledger())
        task.score, task.alerts = candidate_score(plan.brief, spot, weather, task.start, solar, score_ledger, task.id + suffix)
        ledger.sources.extend(score_ledger.sources)
        ledger.evidence.extend(score_ledger.evidence)
    if not material:
        return None
    changed.sources.extend(ledger.sources)
    changed.evidence.extend(ledger.evidence)
    return PlanChangeProposal(id=uuid4().hex, plan_id=plan.id, base_version=plan.version, reason="天气发生材料变化",
        proposed=ShotPlan.model_validate(changed.model_dump()),
        diff=field_diff(plan.model_dump(mode="json"), changed.model_dump(mode="json")))
