"""Deterministic astronomy, evidence, safety, lens selection and scheduling."""
import math
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from astral import Observer, SunDirection
from astral.sun import blue_hour, golden_hour, sun

from .models import (
    CameraAdvice,
    CrowdSignal,
    Evidence,
    HourlyCondition,
    Lens,
    PhotoSpot,
    ScoreBreakdown,
    SolarWindow,
    TripBrief,
    TripNotebook,
    TruthLabel,
    WebSource,
)

RULE_VERSION = "photo-rules/1.2"
WEIGHTS = {
    "portrait": {"光质": .30, "舒适度": .25, "稳定性": .15, "构图": .20, "客流": .10},
    "cityscape": {"蓝调": .30, "能见度": .25, "稳定性": .20, "空气": .10, "构图": .15},
    "landscape": {"光质": .30, "能见度": .25, "稳定性": .20, "构图": .20, "客流": .05},
    "humanities": {"光质": .20, "舒适度": .20, "稳定性": .10, "构图": .25, "客流": .25},
    "architecture": {"光质": .20, "能见度": .20, "稳定性": .20, "构图": .30, "空气": .10},
    "nature": {"光质": .25, "舒适度": .15, "稳定性": .25, "构图": .20, "客流": .15},
}


def notebook(brief: TripBrief) -> TripNotebook:
    data = brief.model_dump()
    data["intent"]["equipment"] = {k: data[k] for k in ("lenses", "sensor", "tripod")}
    result = TripBrief.model_validate(data)
    fields = {"destination": "你准备在哪个城市、景区拍摄？", "travel_date": "请确认具体拍摄日期。",
              "start_local": "当天几点开始拍摄？", "end_local": "当天几点结束拍摄？"}
    missing = [f for f in fields if not getattr(result, f)]
    return TripNotebook(brief=result, missing_fields=missing, questions=[fields[f] for f in missing],
        assumptions=["未提到的条件沿用默认值；推荐偏好通常影响排序，不删除候选。",
                     "开放、预约与精确站位请出发前复核。"])


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
        # Astral interprets date in tzinfo: using UTC moved China's sunrise to
        # the following local day. Calculate the requested local calendar first.
        zone = ZoneInfo(brief.timezone)
        times = sun(observer, date=brief.travel_date, tzinfo=zone)
        gs, _ = golden_hour(observer, date=brief.travel_date, direction=SunDirection.SETTING, tzinfo=zone)
        bs, be = blue_hour(observer, date=brief.travel_date, direction=SunDirection.SETTING, tzinfo=zone)
        result = {k: v.astimezone(UTC) for k, v in {"sunrise": times["sunrise"],
                  "sunset": times["sunset"], "golden_start": gs, "blue_start": bs, "blue_end": be}.items()}
    except ValueError:
        pass  # Polar day/night: no fabricated solar window.
    ids = ledger.add("solar", "Astral 3.2 · 太阳几何", TruthLabel.CALCULATED,
                     "根据日期与目的地区域坐标计算；蓝调定义为太阳高度 -4° 至 -6°。",
                     {"lat": position.lat, "lon": position.lon,
                      **{k: v.isoformat() for k, v in result.items()}},
                     "https://astral.readthedocs.io/en/latest/")
    return SolarWindow(**result, evidence_ids=ids)


def gate(spot: PhotoSpot, weather: HourlyCondition, brief: TripBrief, start, end) -> str | None:
    # Only access facts can exclude a place. Weather, conflict and unknowns are risks.
    if spot.access == "CLOSED":
        return "已确认无法访问，暂不纳入候选"
    if spot.open_from and end <= spot.open_from or spot.open_until and start >= spot.open_until:
        return "所选时段与已知开放窗口不相交"
    preferences = brief.intent.preferences
    if "free" in preferences.strict and spot.ticket_required is True:
        return "已知需要门票，不符合用户明确的只推荐免费地点要求"
    if "step_free" in preferences.strict and spot.step_free is False:
        return "已知存在台阶，不符合用户明确的无台阶要求"
    return None


def fresh_crowd(signal: CrowdSignal, at: datetime) -> CrowdSignal:
    if signal.valid_until and at > signal.valid_until:
        return signal.model_copy(update={"level": "UNKNOWN", "label": TruthLabel.STALE})
    if signal.source_type in ("road_traffic", "heatmap_renderer"):
        return signal.model_copy(update={"level": "UNKNOWN", "label": TruthLabel.UNKNOWN})
    return signal


def camera_advice(brief, index, ledger):
    is_phone = brief.sensor == "phone"
    lenses = brief.lenses or [Lens(name="手机摄像头" if is_phone else "未指定器材（通用起点）", min_mm=24, max_mm=24, max_aperture=1.8 if is_phone else 4)]
    lens = lenses[index % len(lenses)]
    crop = {"full_frame": 1, "aps_c": 1.5, "m43": 2, "phone": 1}[brief.sensor]
    if is_phone:
        crop = 1
    target = 35 if index % 2 == 0 else 85
    focal = max(lens.min_mm, min(lens.max_mm, target / crop))
    eq = focal * crop
    if brief.intent.categories == ["portrait"] and brief.intent.light not in ("night", "blue_hour"):
        aperture, shutter, iso = max(lens.max_aperture, 2.8), 1 / max(250, 2 * eq), 200
        adjustment = "人物虚则提高快门，再提高 ISO；多人合照缩小光圈。现场对脸测光，曝光只是起点。"
    elif brief.intent.light not in ("night", "blue_hour"):
        aperture, shutter, iso = max(lens.max_aperture, 5.6), 1 / max(125, 2 * eq), 200
        adjustment = "日间曝光起点：建筑与风光优先景深，人文活动提高快门；按现场测光调整 ISO。"
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
    blue = .95 if solar.blue_start and solar.blue_end and solar.blue_start <= start <= solar.blue_end else .65
    features = {"光质": light, "舒适度": max(.1, 1 - abs((weather.temperature_c or 24) - 22) / 25),
                "稳定性": stable, "构图": .75, "客流": .5, "蓝调": blue,
                "能见度": min(1, (weather.visibility_m or 5000) / 20000),
                "空气": max(.1, 1 - (weather.aqi or 75) / 200)}
    categories = brief.intent.categories
    weights = {}
    for category in categories:
        for feature, weight in WEIGHTS[category].items():
            weights[feature] = weights.get(feature, 0) + weight / len(categories)
    components = {feature: features[feature] for feature in weights}
    suitability = round(100 * math.exp(sum(weights[k] * math.log(v) for k, v in components.items())), 1)
    values = {"suitability": suitability, "components": components, "weights": weights,
              "confidence": round(.35 * known / 5 + .15, 2)}
    ids = ledger.add(f"score-{index}", RULE_VERSION, TruthLabel.INFERRED,
                     "题材加权几何平均；未知维度使用中性起点。置信度独立，区域与开放未核验会降低置信度。", values)
    return ScoreBreakdown(**values, evidence_ids=ids)


def build_plan(plan_id, brief, spots, claims, conditions, routes, ledger, warnings):
    """Compatibility entry for old callers; all recommendations use one evaluator."""
    from .recommendations import build_recommendations
    return build_recommendations(plan_id, brief, spots, claims, {s.id: conditions for s in spots}, ledger, warnings)
