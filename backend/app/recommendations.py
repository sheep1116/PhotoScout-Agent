"""Independent viewpoint evaluation; ranking is not an itinerary."""
import math
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import azimuth

from .engine import Ledger, bearing, camera_advice, gate, score, solar_windows
from .models import AgentAnswer, CrowdSignal, ShotPlan, ShotTask, SolarWindow, TruthLabel


def window(brief):
    zone = ZoneInfo(brief.timezone)
    return (datetime.combine(brief.travel_date, brief.start_local, zone).astimezone(UTC),
            datetime.combine(brief.end_date or brief.travel_date, brief.end_local, zone).astimezone(UTC))


def candidate_gate(spot, weather, brief, start, end):
    return gate(spot, weather, brief, start, end)


def distance_km(a, b, c, d):
    lat1, lat2 = math.radians(a), math.radians(c)
    value = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(math.radians(d-b)/2)**2
    return round(6371 * 2 * math.asin(min(1, math.sqrt(value))), 2)


def circular_span(values):
    """Smallest compass arc containing all bearings."""
    values = sorted(value % 360 for value in values)
    if len(values) < 2:
        return None
    gaps = [values[i + 1] - values[i] for i in range(len(values) - 1)] + [values[0] + 360 - values[-1]]
    return round(360 - max(gaps), 1)


def reference_weather_penalty(weather, reference):
    target = (reference or {}).get('weather', 'unknown')
    if target == 'overcast' and weather.cloud_pct is not None:
        return -max(0, 70-weather.cloud_pct)/3
    if target == 'clear' and weather.cloud_pct is not None:
        return -max(0, weather.cloud_pct-30)/3
    if target == 'rain' and weather.precipitation_mm == 0:
        return -18
    if target == 'fog' and weather.visibility_m is not None and weather.visibility_m > 2000:
        return -18
    if target == 'snow' and weather.weather_code is not None and weather.weather_code not in (71,73,75,77,85,86):
        return -18
    return 0


def build_recommendations(plan_id, brief, spots, claims, weather_by_spot, ledger, warnings, reference=None,
                          agent_answer=None):
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
        if spot.open_from and begin <= spot.open_from < finish:
            samples.add(spot.open_from)
        for cursor in sorted(samples):
            if spot.open_from and cursor < spot.open_from:
                reason = "尚未到已知开放时间"
                continue
            if spot.open_until and cursor >= spot.open_until:
                reason = "已超出已知开放时间"
                continue
            local_date = cursor.astimezone(ZoneInfo(brief.timezone)).date()
            if local_date not in solars:
                solar_brief = brief.model_copy(update={"travel_date": local_date})
                solars[local_date] = solar_windows(solar_brief, spot.camera, ledger)
            solar = solars[local_date]
            primary_solar = primary_solar or solar
            conditions = weather_by_spot[spot.id]
            weather = min(conditions, key=lambda w: abs((w.at-cursor).total_seconds()))
            end = min(finish, cursor + timedelta(minutes=30), spot.open_until or finish)
            preference = brief.intent.light if brief.intent else "any"
            if preference == "blue_hour" and solar.blue_start and solar.blue_end and solar.blue_start <= cursor < solar.blue_end:
                end = min(end, solar.blue_end)
            elif preference in ("daylight", "golden_hour") and solar.sunset and cursor < solar.sunset:
                end = min(end, solar.sunset)
            reason = candidate_gate(spot, weather, brief, cursor, end)
            anchors = {"sunrise": solar.sunrise, "golden_hour": solar.golden_start,
                       "blue_hour": solar.blue_start, "night": solar.blue_end}
            if not reason:
                anchor = anchors.get(preference)
                quality = candidate_score(brief, spot, weather, cursor, solar, Ledger(), index)[0].suitability
                quality += reference_weather_penalty(weather, reference)
                if anchor:
                    quality -= abs((cursor-anchor).total_seconds()) / 1800
                possible.append((quality, cursor, end, weather, solar))
        if not possible:
            excluded.append({"spot": spot.name, "reason": reason or "没有符合条件的拍摄窗口"})
            continue
        _, start, end, weather, solar = max(possible, key=lambda item: item[0])
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
        crowd_ids = ledger.add(f"candidate-crowd-{index}", "客流信息", TruthLabel.UNKNOWN,
                               "暂无游客客流数据；不以客流偏好排除候选。")
        subject_bearings = {subject.name: bearing(spot.camera, subject.position)
                            for subject in spot.subjects if subject.position}
        direction = next(iter(subject_bearings.values()), None)
        subject_span = circular_span(list(subject_bearings.values()))
        camera = camera_advice(advice_brief, index, ledger)
        field_of_view = round(math.degrees(2 * math.atan(36 / (2 * camera.equivalent_mm))), 1) if camera.equivalent_mm else None
        if subject_span is None:
            framing_assessment = "缺少至少两个可定位主体，暂不能核验同框范围。"
        elif field_of_view and subject_span <= field_of_view:
            framing_assessment = f"两主体方位跨度约 {subject_span}°，小于当前焦段约 {field_of_view}° 的水平视角；平面几何上可同框，遮挡仍待现场确认。"
        else:
            framing_assessment = f"两主体方位跨度约 {subject_span}°，大于当前焦段约 {field_of_view}° 的水平视角；建议缩短焦段或调整站位。"
        solar_angle = round(azimuth(Observer(spot.camera.lat, spot.camera.lon), start), 1)
        geometry = ledger.add(f"candidate-geometry-{index}", "机位方向与时间窗口", TruthLabel.CALCULATED,
            "每个机位独立评估；窗口可重叠，不代表访问顺序。方位角不保证视线无遮挡。",
            {"start": start.isoformat(), "end": end.isoformat(), "target_bearing_deg": direction,
             "subject_bearings_deg": subject_bearings, "subject_separation_deg": subject_span,
             "field_of_view_deg": field_of_view, "solar_azimuth_deg": solar_angle})
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
        ranking, alerts = candidate_score(brief, spot, weather, start, solar, ledger, index)
        if reference:
            adjustment = round(reference_weather_penalty(weather, reference), 1)
            ranking.suitability = round(max(0, ranking.suitability+adjustment), 1)
            ranking.adjustments['参考天气匹配'] = adjustment
            ranking.evidence_ids += ledger.add(f'reference-weather-{index}', '参考天气匹配规则', TruthLabel.INFERRED,
                '参考天气是视觉推断；按预报比较相似性，不保证还原画面。', {'reference':reference,'adjustment':adjustment,'suitability':ranking.suitability})
            if adjustment < 0:
                alerts.append('天气预报与参考照片推断的条件不同，复刻效果可能有差异。')
        risks = list(spot.risks) + alerts
        if spot.access != "OPEN":
            risks.append("开放、预约及管制未获有效官方确认，推荐暂定。")
        if weather.label == "UNKNOWN":
            risks.append("天气未知，时间仅为天文与可用时段建议。")
        if weather.at < start-timedelta(minutes=90) or weather.at > end+timedelta(minutes=90):
            risks.append("天气快照与推荐窗口距离较远，请刷新后确认。")
        tasks.append(ShotTask(id=f"candidate-{index+1}", spot_id=spot.id, title=spot.name, start=start, end=end,
            status="TENTATIVE", composition=spot.composition, camera=camera,
            weather=weather, crowd=CrowdSignal(spatial_scope=spot.name, evidence_ids=crowd_ids),
            score=ranking, alerts=alerts, solar_azimuth_deg=solar_angle,
            target_bearing_deg=direction, subject_bearings_deg=subject_bearings,
            subject_separation_deg=subject_span, field_of_view_deg=field_of_view,
            framing_assessment=framing_assessment, risks=risks, alternative="条件不合适时暂缓该机位，由你选择其他候选。",
            reasons=["匹配摄影意图：" + " / ".join(brief.intent.categories),
                     "来源线索已关联高德地标；站位精度与开放状态分别标注。" if brief.mode == "live" else "离线示例地标与构图；尚未经过真实来源核验。",
                     "独立比较可用时段的天气和光线，不受其他机位的访问顺序约束。"],
            recommended_light=actual_light, distance_km=distance,
            travel_advice=travel, evidence_ids=spot.camera.evidence_ids + spot.access_evidence_ids + geometry + solar.evidence_ids))
    tasks.sort(key=lambda t: (t.score.suitability, t.score.confidence), reverse=True)
    if primary_solar is None:
        ids = ledger.add("solar-unavailable", "太阳几何待定位", TruthLabel.UNKNOWN,
                         "没有可定位的相机候选，不能计算该机位的太阳与拍摄方向。")
        primary_solar = SolarWindow(evidence_ids=ids)
    if brief.mode == "mock":
        warnings.insert(0, "离线演示：地点、天气与经验为 Fixture，不代表现场情况。")
    warnings.append("候选排名不代表出行顺序；推荐窗口可以重叠，由你决定去哪里、去几个、怎么去。")
    return ShotPlan(id=plan_id, presentation="candidates", brief=brief,
        agent_answer=agent_answer or AgentAnswer(), spots=spots, tasks=tasks, routes=[],
        solar=primary_solar, sources=ledger.sources, claims=claims, evidence=ledger.evidence,
        warnings=warnings, excluded=excluded)


def candidate_score(brief, spot, weather, start, solar, ledger, index):
    ranking = score(brief, weather, start, solar, ledger, index)
    adjustments, alerts = {}, []
    preference = brief.intent.light
    matched = True
    if solar.sunrise and solar.sunset:
        matched = {"daylight": solar.sunrise <= start < solar.sunset,
                   "night": not solar.sunrise <= start < (solar.blue_end or solar.sunset),
                   "golden_hour": bool(solar.golden_start and solar.golden_start <= start <= solar.sunset),
                   "blue_hour": bool(solar.blue_start and solar.blue_end and solar.blue_start <= start <= solar.blue_end),
                   "sunrise": abs((start-solar.sunrise).total_seconds()) <= 900}.get(preference, True)
    if not matched:
        adjustments["光线偏好不匹配"] = -18
        alerts.append("当前时间条件不理想：推荐时段未匹配偏好光线，保留机位供选择。")
    if (weather.precipitation_mm or 0) > 0:
        adjustments["预计降雨"] = -min(30, 8 + weather.precipitation_mm*3)
        alerts.append(f"预计降雨 {weather.precipitation_mm:g} mm；保留机位，出发前复核预报。")
    if brief.intent.light in ("golden_hour", "sunrise") and ((weather.cloud_pct or 0) >= 80 or (weather.precipitation_mm or 0) > 0):
        alerts.append("夕阳/日出可见机会较低：依据降雨或云量的定性提示，不是概率预测。")
        adjustments["直射光机会低"] = -12
    if weather.weather_code in (95, 96, 99) or (weather.wind_kmh or 0) >= 40 or (weather.precipitation_mm or 0) >= 7.5:
        adjustments["危险天气"] = -35
        alerts.append("危险天气：不建议在该时段前往户外；机位仅作之后条件改善时的参考。")
    if spot.unsafe:
        adjustments["站位风险待核验"] = -35
        alerts.append("来源含危险或非公开站位线索，不建议按该线索行动；仅在确认公开安全位置后考虑。")
    if spot.access == "CONFLICT":
        adjustments["开放冲突"] = -20
        alerts.append("开放信息冲突，暂勿前往，需官方确认。")
    if brief.tripod and spot.tripod_allowed is False:
        adjustments["脚架不匹配"] = -10
        alerts.append("该地点不允许三脚架，请改用手持方案或选择其他机位。")
    p = brief.intent.preferences
    if p.avoid_tickets and spot.ticket_required:
        adjustments["门票偏好"] = -12
        alerts.append("此地点可能收费，与不买门票偏好不匹配；未按默认偏好排除。")
    if p.max_walk_km is not None:
        if brief.origin_lat is not None:
            distance = distance_km(brief.origin_lat, brief.origin_lon, spot.camera.lat, spot.camera.lon)
            if distance > p.max_walk_km:
                adjustments["距离偏好"] = -min(20, (distance-p.max_walk_km)*2+5)
                alerts.append(f"距起点直线约 {distance} km，超过低步行量参考值；实际步行与交通方式未核实。")
        else:
            alerts.append("已记录低步行量偏好；缺少起点和可靠路线，暂不计算步行距离或据此过滤。")
    if p.step_free and spot.step_free is not True:
        adjustments["无台阶待核实"] = -8
        alerts.append("无台阶通行尚未证实，请核实入口后决定。")
    if p.low_crowd:
        alerts.append("已记录人少偏好；没有可靠游客客流数据，不用道路交通或热度替代。")
    if p.strict:
        alerts.append("已记录明确要求；未知信息不视作已满足，请复核后选择。")
    # Categories have equal shares; absent spot classifications remain unknown.
    if spot.genres and not set(brief.intent.categories) & set(spot.genres):
        adjustments["题材匹配不足"] = -12
        alerts.append("该地点的已有题材信息与需求不完全匹配，仍保留构图探索机会。")
    ranking.suitability = round(max(0, ranking.suitability + sum(adjustments.values())), 1)
    ranking.adjustments = adjustments
    for evidence in ledger.evidence:
        if evidence.id in ranking.evidence_ids:
            evidence.values.update(suitability=ranking.suitability, adjustments=adjustments)
    return ranking, alerts
