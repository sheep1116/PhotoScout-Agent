"""Deterministic astronomy, evidence, safety, lens selection and scheduling."""
import math
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from astral import Observer, SunDirection
from astral.sun import azimuth, blue_hour, golden_hour, sun

from .models import (
    CameraAdvice,
    CrowdSignal,
    Evidence,
    HourlyCondition,
    Lens,
    PhotoSpot,
    ScoreBreakdown,
    ShotPlan,
    ShotTask,
    SolarWindow,
    TripBrief,
    TripNotebook,
    TruthLabel,
    WebSource,
)

RULE_VERSION = "photo-rules/1.0"
WEIGHTS = {
    "portrait": {"光质": .30, "舒适度": .25, "稳定性": .15, "构图": .20, "客流": .10},
    "cityscape": {"蓝调": .30, "能见度": .25, "稳定性": .20, "空气": .10, "构图": .15},
}


def notebook(brief: TripBrief) -> TripNotebook:
    data = brief.model_dump()
    text = brief.text
    # No guess of relative dates, ambiguous cities or private details.
    if not brief.destination and "南京" in text:
        data["destination"] = "南京紫金山" if "紫金山" in text else "南京"
    if not brief.genre:
        if any(s in text for s in ["人像", "合照", "女朋友"]):
            data["genre"] = "portrait"
        elif any(s in text for s in ["夜景", "天际线", "蓝调"]):
            data["genre"] = "cityscape"
    if not brief.travel_date and (match := re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)):
        try:
            data["travel_date"] = datetime.strptime(match[1], "%Y-%m-%d").date()
        except ValueError:
            pass
    result = TripBrief.model_validate(data)
    fields = {"destination": "你准备在哪个城市、景区拍摄？", "travel_date": "请确认具体拍摄日期。",
              "genre": "想拍旅行人像，还是城市夜景？", "start_local": "当天几点开始拍摄？",
              "end_local": "当天几点结束拍摄？"}
    missing = [f for f in fields if not getattr(result, f)]
    assumptions = ["开放、预约和精确站位需要出发前及现场复核。", "未提供的偏好使用表单中展示的默认值。"]
    if not result.lenses:
        assumptions.append("未填写镜头：使用手机主摄 24mm 等效；光圈由设备决定。")
    return TripNotebook(brief=result, missing_fields=missing,
                        questions=[fields[f] for f in missing], assumptions=assumptions)


class Ledger:
    def __init__(self):
        self.sources: list[WebSource] = []
        self.evidence: list[Evidence] = []

    def add(self, key, title, label, statement, values=None, url=None, kind="tool", valid_until=None):
        sid = f"src-{key}"
        if not any(s.id == sid for s in self.sources):
            self.sources.append(WebSource(id=sid, url=url, title=title, publisher=title, kind=kind))
        eid = f"ev-{key}"
        existing = {e.id for e in self.evidence}
        if eid in existing:
            eid = f"{eid}-{len(existing)}"
        self.evidence.append(Evidence(id=eid, source_id=sid, label=label, statement=statement,
                                     values=values or {}, valid_until=valid_until))
        return [eid]


def solar_windows(brief, position, ledger):
    observer = Observer(position.lat, position.lon)
    result = {}
    try:
        times = sun(observer, date=brief.travel_date, tzinfo=UTC)
        gs, _ = golden_hour(observer, date=brief.travel_date, direction=SunDirection.SETTING, tzinfo=UTC)
        bs, be = blue_hour(observer, date=brief.travel_date, direction=SunDirection.SETTING, tzinfo=UTC)
        result = {"sunrise": times["sunrise"], "sunset": times["sunset"], "golden_start": gs,
                  "blue_start": bs, "blue_end": be}
    except ValueError:
        pass  # Polar day/night: no fabricated solar window.
    ids = ledger.add("solar", "Astral 3.2 · 太阳几何", TruthLabel.CALCULATED,
                     "根据日期与目的地区域坐标计算；蓝调定义为太阳高度 -4° 至 -6°。",
                     {"lat": position.lat, "lon": position.lon,
                      **{k: v.isoformat() for k, v in result.items()}},
                     "https://astral.readthedocs.io/en/latest/")
    return SolarWindow(**result, evidence_ids=ids)


def gate(spot: PhotoSpot, weather: HourlyCondition, brief: TripBrief, start, end) -> str | None:
    if spot.unsafe:
        return "危险或非公开站位，已排除"
    if spot.access == "CLOSED":
        return "关闭状态，已排除"
    if spot.access == "CONFLICT":
        return "开放来源冲突，暂停该机位，等待核验"
    if spot.ticket_required and not brief.accept_tickets:
        return "需要门票或预约，与当前偏好不符"
    if spot.open_from and start < spot.open_from or spot.open_until and end > spot.open_until:
        return "拍摄时间超出已知开放窗口"
    if weather.weather_code in [95, 96, 99]:
        return "雷暴，取消户外拍摄"
    if weather.wind_kmh is not None and weather.wind_kmh >= 40:
        return "大风，取消户外拍摄"
    if weather.precipitation_mm is not None and weather.precipitation_mm >= 7.5:
        return "强降水，取消户外拍摄"
    if brief.profile == "family" and weather.temperature_c is not None and not 5 <= weather.temperature_c <= 35:
        return "温度不适合轻量家庭户外行程"
    if brief.genre == "cityscape" and weather.visibility_m is not None and weather.visibility_m < 1000:
        return "远景能见度不足"
    if brief.genre == "cityscape" and brief.tripod and spot.tripod_allowed is False:
        return "机位禁止三脚架，与长曝光要求冲突"
    return None


def fresh_crowd(signal: CrowdSignal, at: datetime) -> CrowdSignal:
    if signal.valid_until and at > signal.valid_until:
        return signal.model_copy(update={"level": "UNKNOWN", "label": TruthLabel.STALE})
    if signal.source_type in ("road_traffic", "heatmap_renderer"):
        return signal.model_copy(update={"level": "UNKNOWN", "label": TruthLabel.UNKNOWN})
    return signal


def camera_advice(brief, index, ledger):
    is_phone = brief.sensor == "phone" or not brief.lenses
    lenses = brief.lenses or [Lens(name="手机主摄", min_mm=24, max_mm=24, max_aperture=1.8)]
    lens = lenses[index % len(lenses)]
    crop = {"full_frame": 1, "aps_c": 1.5, "m43": 2, "phone": 1}[brief.sensor]
    if is_phone:
        crop = 1
    target = 35 if index % 2 == 0 else 85
    focal = max(lens.min_mm, min(lens.max_mm, target / crop))
    eq = focal * crop
    if brief.genre == "portrait":
        aperture, shutter, iso = max(lens.max_aperture, 2.8 if brief.profile != "family" else 5.6), 1 / max(250, 2 * eq), 200
        adjustment = "人物虚则提高快门，再提高 ISO；多人合照缩小光圈。现场对脸测光，曝光只是起点。"
    elif brief.tripod:
        aperture, shutter, iso = max(8, lens.max_aperture), 2, 100
        adjustment = "从 1–4 秒试拍；查看高光直方图，灯光溢出则缩短快门。RAW，-2/0/+2 EV 包围曝光。"
    else:
        aperture, shutter, iso = lens.max_aperture, 1 / max(60, 2 * eq), 1600
        adjustment = "ISO 可从 800–6400 按需调整；短连拍检查清晰度，长焦时提高快门。"
    if is_phone:
        aperture = lens.max_aperture
        adjustment = "使用主摄，长按锁定对焦与曝光，降低曝光补偿保护高光。手机自动档管理快门与 ISO，固定光圈无需设置。"
    values = dict(lens=lens.name, focal_mm=round(focal, 1), equivalent_mm=round(eq, 1),
                  aperture=aperture, shutter_seconds=shutter, iso=iso)
    ids = ledger.add(f"camera-{index}", RULE_VERSION, TruthLabel.INFERRED,
                     "规则产生的曝光建议起点；没有现场测光，不保证曝光。", values)
    return CameraAdvice(**values, adjustment=adjustment, evidence_ids=ids)


def bearing(a, b):
    lat1, lat2, delta = math.radians(a.lat), math.radians(b.lat), math.radians(b.lon - a.lon)
    return round((math.degrees(math.atan2(math.sin(delta) * math.cos(lat2),
        math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta))) + 360) % 360, 1)


def score(brief, weather, start, solar, ledger, index):
    known = sum(getattr(weather, k) is not None for k in
                ["temperature_c", "precipitation_mm", "wind_kmh", "visibility_m", "aqi"])
    stable = max(.1, 1 - (weather.wind_kmh or 15) / 50)
    light = .65
    if solar.golden_start and solar.sunset and solar.golden_start <= start <= solar.sunset:
        light = .95
    if brief.genre == "portrait":
        components = {"光质": light, "舒适度": max(.1, 1 - abs((weather.temperature_c or 24) - 22) / 25),
                      "稳定性": stable, "构图": .75, "客流": .5}
    else:
        blue = .95 if solar.blue_start and solar.blue_end and solar.blue_start <= start <= solar.blue_end else .65
        components = {"蓝调": blue, "能见度": min(1, (weather.visibility_m or 5000) / 20000),
                      "稳定性": stable, "空气": max(.1, 1 - (weather.aqi or 75) / 200), "构图": .75}
    weights = WEIGHTS[brief.genre]
    suitability = round(100 * math.exp(sum(weights[k] * math.log(v) for k, v in components.items())), 1)
    values = {"suitability": suitability, "components": components, "weights": weights,
              "confidence": round(.35 * known / 5 + .15, 2)}
    ids = ledger.add(f"score-{index}", RULE_VERSION, TruthLabel.INFERRED,
                     "题材加权几何平均；未知维度使用中性起点。置信度独立，区域与开放未核验会降低置信度。", values)
    return ScoreBreakdown(**values, evidence_ids=ids)


def build_plan(plan_id, brief, spots, claims, conditions, routes, ledger, warnings):
    solar = solar_windows(brief, spots[0].camera, ledger)
    zone = ZoneInfo(brief.timezone)
    begin = datetime.combine(brief.travel_date, brief.start_local, zone).astimezone(UTC)
    finish = datetime.combine(brief.travel_date, brief.end_local, zone).astimezone(UTC)
    preferred = solar.golden_start - timedelta(minutes=70) if brief.genre == "portrait" and solar.golden_start else begin
    if brief.genre == "cityscape" and solar.sunset:
        preferred = solar.sunset - timedelta(minutes=40)
    cursor = max(begin, min(preferred, finish - timedelta(minutes=120)))
    tasks, excluded, used_routes = [], [], []
    total_walk = 0
    prior = None
    sequence = spots
    if brief.mode == "live" and not routes:
        # A stationary series is feasible even when inter-spot entrances are unknown.
        safe = next((s for s in spots if not gate(s, conditions[0], brief, cursor,
                    cursor + timedelta(minutes=25))), None)
        sequence = [safe] * 3 if safe else spots
        warnings.append("缺少已核验入口路线：采用单区域拍摄序列，不安排未经验证的跨区域移动。")
    for spot in sequence:
        if len(tasks) >= (3 if brief.profile == "family" else 4):
            break
        leg = next((r for r in routes if prior and r.from_id == prior.id and r.to_id == spot.id), None)
        if prior and prior.id != spot.id and (not leg or leg.duration_min is None or leg.distance_m is None):
            excluded.append({"spot": spot.name, "reason": "换点路线未知，不拼接不可验证行程"})
            continue
        if leg and total_walk + leg.distance_m > brief.max_walk_km * 1000:
            excluded.append({"spot": spot.name, "reason": "超出步行预算"})
            continue
        start = cursor + timedelta(minutes=(leg.duration_min + 10 if leg else 0))
        end = start + timedelta(minutes=25)
        if end > finish:
            excluded.append({"spot": spot.name, "reason": "可用时间不足"})
            continue
        weather = min(conditions, key=lambda w: abs((w.at - start).total_seconds()))
        reason = gate(spot, weather, brief, start, end)
        if reason:
            excluded.append({"spot": spot.name, "reason": reason})
            continue
        index = len(tasks)
        crowd_ids = ledger.add(f"crowd-{index}", "客流能力边界", TruthLabel.UNKNOWN,
                               "没有可用的游客客流源；道路交通和热力图不代表游客客流。")
        crowd = CrowdSignal(spatial_scope=spot.name, evidence_ids=crowd_ids)
        az = round(azimuth(Observer(spot.camera.lat, spot.camera.lon), start), 1)
        target = spot.subjects[0].position if spot.subjects else None
        direction = bearing(spot.camera, target) if target else None
        geom_ids = ledger.add(f"geometry-{index}", "太阳与目标方向", TruthLabel.CALCULATED,
                              "区域坐标计算的示意方向，不是实测构图射线。",
                              {"solar_azimuth_deg": az, "target_bearing_deg": direction})
        time_ids = ledger.add(f"schedule-{index}", RULE_VERSION, TruthLabel.INFERRED,
                              "25 分钟任务；换点加入路线时长和 10 分钟缓冲；首站到达交通另行安排。",
                              {"start": start.isoformat(), "end": end.isoformat(),
                               "route_basis": leg.evidence_ids if leg else "首站，无换点路线"})
        ready = spot.access == "OPEN" and spot.camera.precision == "EXACT_VERIFIED" and weather.label == "REPORTED"
        risks = list(spot.risks)
        if spot.access in ["UNKNOWN", "CONFLICT"]:
            risks.append("开放/预约/临时管制未经官方当日复核，暂定任务，确认后再出发。")
        if spot.camera.precision != "EXACT_VERIFIED":
            risks.append("仅定位到区域或 POI；请在公开步行区域确认站位。")
        if weather.label == "UNKNOWN":
            risks.append("天气未知：时间仅基于天文与可用时段，不能称为实时最佳窗口。")
        tasks.append(ShotTask(id=f"shot-{index + 1}", spot_id=spot.id,
            title=f"{spot.name} · {['环境叙事', '光影特写', '细节收集', '创意收尾'][index]}",
            start=start, end=end, status="READY" if ready else "TENTATIVE", composition=spot.composition,
            camera=camera_advice(brief, index, ledger), weather=weather, crowd=crowd,
            score=score(brief, weather, start, solar, ledger, index), solar_azimuth_deg=az,
            target_bearing_deg=direction, risks=risks,
            alternative="若下雨或关闭：取消本段户外任务；在已确认安全的室内整理照片，不自动导航到未核验替代地点。",
            evidence_ids=spot.camera.evidence_ids + spot.access_evidence_ids + time_ids + geom_ids))
        if leg:
            used_routes.append(leg)
            total_walk += leg.distance_m
        cursor, prior = end, spot
    if not tasks:
        warnings.append("没有满足当前时间、器材、路线或安全条件的任务；请调整条件或取消户外拍摄。")
    if brief.mode == "mock":
        warnings.insert(0, "离线演示：天气、路线与来源示例均为 Fixture，不代表目的地真实现状。")
    warnings.append("首站到达与末站返程未计入步行预算；请另行安排交通。")
    return ShotPlan(id=plan_id, brief=brief, spots=spots, tasks=tasks, routes=used_routes, solar=solar,
                    sources=ledger.sources, claims=claims, evidence=ledger.evidence, warnings=warnings,
                    excluded=excluded)
