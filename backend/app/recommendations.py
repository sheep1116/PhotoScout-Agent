"""Independent viewpoint evaluation; ranking is not an itinerary."""
import math
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import azimuth

from .engine import Ledger, bearing, camera_advice, gate, score, solar_windows
from .models import CrowdSignal, ShotPlan, ShotTask, TruthLabel


def window(brief):
    zone = ZoneInfo(brief.timezone)
    return (datetime.combine(brief.travel_date, brief.start_local, zone).astimezone(UTC),
            datetime.combine(brief.end_date or brief.travel_date, brief.end_local, zone).astimezone(UTC))


def candidate_gate(spot, weather, brief, start, end):
    # Transport preferences are advice, not eligibility constraints.
    relaxed = brief.model_copy(deep=True)
    relaxed.accept_tickets = True
    relaxed.profile = "enthusiast"
    if relaxed.intent:
        relaxed.intent.mobility = "standard"
    return gate(spot, weather, relaxed, start, end)


def distance_km(a, b, c, d):
    lat1, lat2 = math.radians(a), math.radians(c)
    value = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(math.radians(d-b)/2)**2
    return round(6371 * 2 * math.asin(min(1, math.sqrt(value))), 2)


def build_recommendations(plan_id, brief, spots, claims, weather_by_spot, ledger, warnings):
    begin, finish = window(brief)
    tasks, excluded = [], []
    primary_solar = None
    for index, spot in enumerate(spots):
        # Each spot has its own solar/date and forecast snapshots, never the previous spot's schedule.
        possible, solars = [], {}
        samples = set()
        cursor = begin
        preference = brief.intent.light if brief.intent else "any"
        while cursor < finish:
            samples.add(cursor)
            cursor += timedelta(minutes=30)
        for day in {t.astimezone(ZoneInfo(brief.timezone)).date() for t in samples}:
            solars[day] = solar_windows(brief.model_copy(update={"travel_date": day}), spot.camera, ledger)
            anchor = {"sunrise": solars[day].sunrise, "golden_hour": solars[day].golden_start,
                      "blue_hour": solars[day].blue_start, "night": solars[day].blue_end}.get(preference)
            if anchor and begin <= anchor < finish:
                samples.add(anchor)
        reason = None
        for cursor in sorted(samples):
            local_date = cursor.astimezone(ZoneInfo(brief.timezone)).date()
            if local_date not in solars:
                solar_brief = brief.model_copy(update={"travel_date": local_date})
                solars[local_date] = solar_windows(solar_brief, spot.camera, ledger)
            solar = solars[local_date]
            primary_solar = primary_solar or solar
            conditions = weather_by_spot[spot.id]
            weather = min(conditions, key=lambda w: abs((w.at-cursor).total_seconds()))
            end = min(finish, cursor + timedelta(minutes=30))
            preference = brief.intent.light if brief.intent else "any"
            if preference == "blue_hour" and solar.blue_start and solar.blue_end and solar.blue_start <= cursor < solar.blue_end:
                end = min(end, solar.blue_end)
            elif preference in ("daylight", "golden_hour") and solar.sunset and cursor < solar.sunset:
                end = min(end, solar.sunset)
            reason = candidate_gate(spot, weather, brief, cursor, end)
            anchors = {"sunrise": solar.sunrise, "golden_hour": solar.golden_start,
                       "blue_hour": solar.blue_start, "night": solar.blue_end}
            if preference == "daylight" and solar.sunrise and solar.sunset and not solar.sunrise <= cursor < solar.sunset:
                reason = reason or "所选时段没有日间光线"
            if preference == "night" and solar.sunrise and solar.blue_end and solar.sunrise <= cursor < solar.blue_end:
                reason = reason or "所选时段尚未入夜"
            if not reason:
                anchor = anchors.get(preference)
                quality = score(brief, weather, cursor, solar, Ledger(), index).suitability
                if anchor:
                    quality -= abs((cursor-anchor).total_seconds()) / 1800
                possible.append((quality, cursor, end, weather, solar))
        if not possible:
            excluded.append({"spot": spot.name, "reason": reason or "没有符合条件的拍摄窗口"})
            continue
        def preferred(item):
            _, at, _, _, sun = item
            if preference == "blue_hour":
                return bool(sun.blue_start and sun.blue_end and sun.blue_start <= at <= sun.blue_end)
            if preference == "golden_hour":
                return bool(sun.golden_start and sun.sunset and sun.golden_start <= at <= sun.sunset)
            if preference == "sunrise":
                return bool(sun.sunrise and abs((at-sun.sunrise).total_seconds()) <= 900)
            return True
        _, start, end, weather, solar = max(possible, key=lambda item: (preferred(item), item[0]))
        actual_light = "daylight"
        if solar.sunrise and solar.sunset and not solar.sunrise <= start <= solar.sunset:
            actual_light = "night"
        if solar.golden_start and solar.sunset and solar.golden_start <= start <= solar.sunset:
            actual_light = "golden_hour"
        if solar.blue_start and solar.blue_end and solar.blue_start <= start <= solar.blue_end:
            actual_light = "blue_hour"
        advice_brief = brief.model_copy(deep=True)
        if advice_brief.intent:
            advice_brief.intent.light = actual_light
        if actual_light == "daylight" and advice_brief.genre == "cityscape":
            advice_brief.genre = "architecture"
        crowd_ids = ledger.add(f"candidate-crowd-{index}", "客流信息", TruthLabel.UNKNOWN,
                               "暂无游客客流数据；不以客流偏好排除候选。")
        target = spot.subjects[0].position if spot.subjects else None
        direction = bearing(spot.camera, target) if target else None
        solar_angle = round(azimuth(Observer(spot.camera.lat, spot.camera.lon), start), 1)
        geometry = ledger.add(f"candidate-geometry-{index}", "机位方向与时间窗口", TruthLabel.CALCULATED,
            "每个机位独立评估；窗口可重叠，不代表访问顺序。方位角不保证视线无遮挡。",
            {"start": start.isoformat(), "end": end.isoformat(), "target_bearing_deg": direction,
             "solar_azimuth_deg": solar_angle})
        distance = None
        travel = ["停车、爬升、入口与实际步行时间暂无可靠数据，请出发前查看地图。"]
        if brief.origin_lat is not None:
            distance = distance_km(brief.origin_lat, brief.origin_lon, spot.camera.lat, spot.camera.lon)
            next(e for e in ledger.evidence if e.id == geometry[0]).values["straight_line_distance_km"] = distance
            travel.insert(0, f"距定位起点直线约 {distance} km；不是道路距离或步行耗时。")
        if spot.ticket_required:
            travel.append("可能需要门票或预约，请查看官方渠道。")
        if spot.step_free is not True:
            travel.append("无台阶通行未核实，推车或轮椅出行请先确认入口。")
        risks = list(spot.risks)
        if not any(preferred(item) for item in possible):
            risks.append("可用时间内未匹配偏好的光线，已提供其他可用时段；请核对实际光线。")
        if spot.access != "OPEN":
            risks.append("开放、预约及管制未获有效官方确认，推荐暂定。")
        if weather.label == "UNKNOWN":
            risks.append("天气未知，时间仅为天文与可用时段建议。")
        if weather.at < start-timedelta(minutes=90) or weather.at > end+timedelta(minutes=90):
            risks.append("天气快照与推荐窗口距离较远，请刷新后确认。")
        tasks.append(ShotTask(id=f"candidate-{index+1}", spot_id=spot.id, title=spot.name, start=start, end=end,
            status="TENTATIVE", composition=spot.composition, camera=camera_advice(advice_brief, index, ledger),
            weather=weather, crowd=CrowdSignal(spatial_scope=spot.name, evidence_ids=crowd_ids),
            score=score(brief, weather, start, solar, ledger, index), solar_azimuth_deg=solar_angle,
            target_bearing_deg=direction, risks=risks, alternative="条件不合适时暂缓该机位，由你选择其他候选。",
            reasons=["匹配摄影意图：" + " / ".join(brief.intent.categories if brief.intent else [brief.genre]),
                     "来源线索已关联高德地标；站位精度与开放状态分别标注。" if brief.mode == "live" else "离线示例地标与构图；尚未经过真实来源核验。",
                     "独立比较可用时段的天气和光线，不受其他机位的访问顺序约束。"],
            recommended_light=actual_light, distance_km=distance,
            travel_advice=travel, evidence_ids=spot.camera.evidence_ids + spot.access_evidence_ids + geometry + solar.evidence_ids))
    tasks.sort(key=lambda t: (t.score.suitability, t.score.confidence), reverse=True)
    if primary_solar is None:
        primary_solar = solar_windows(brief, spots[0].camera, ledger)
    if brief.mode == "mock":
        warnings.insert(0, "离线演示：地点、天气与经验为 Fixture，不代表现场情况。")
    warnings.append("候选排名不代表出行顺序；推荐窗口可以重叠，由你决定去哪里、去几个、怎么去。")
    return ShotPlan(id=plan_id, presentation="candidates", brief=brief, spots=spots, tasks=tasks, routes=[],
        solar=primary_solar, sources=ledger.sources, claims=claims, evidence=ledger.evidence,
        warnings=warnings, excluded=excluded)
