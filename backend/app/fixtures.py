"""Explicit synthetic scenarios; never represented as fetched official/community posts."""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .models import (
    HourlyCondition,
    PhotoSpot,
    PlaceEntity,
    Position,
    RouteLeg,
    SourceClaim,
    Subject,
    TruthLabel,
)

SEEDS = {
    "portrait": [
        ("梧桐大道", 32.0520, 118.8450, "步行区树列", "从公开人行道取景，树列形成纵深；人物留在步行区域。"),
        ("美龄宫周边", 32.0523, 118.8483, "园林与建筑", "选择林荫背景，用环境人像交代建筑与人物关系。"),
        ("四方城周边", 32.0543, 118.8506, "石刻与林间光影", "用前景叶片形成层次，长焦收取人物神态。"),
        ("音乐台周边", 32.0584, 118.8542, "弧形建筑", "保留建筑线条；动物出现与活动情况不作保证。"),
    ],
    "cityscape": [
        ("解放门周边", 32.0603, 118.7968, "紫峰与城墙", "在地面公开步行区域寻找城墙与远处城市的层次，避免边缘站位。"),
        ("玄武湖西南岸", 32.0620, 118.7960, "湖面与天际线", "用湖面作前景，等待蓝调光比，亮灯时间需要复核。"),
        ("玄武湖环湖步道", 32.0643, 118.7943, "城市倒影", "广角保留水面；长焦压缩远处建筑，避开主通道架脚架。"),
        ("玄武门周边", 32.0672, 118.7909, "城门与城市光影", "收取城门线条与街道细节，保护高光。"),
    ],
}


def seed_spots(brief, ledger):
    spots, claims = [], []
    for index, (name, lat, lon, subject, composition) in enumerate(SEEDS["cityscape" if "cityscape" in brief.intent.categories else "portrait"]):
        sid = f"seed-{'-'.join(brief.intent.categories)}-{index}"
        ids = ledger.add(sid, f"离线 Seed · {name}", TruthLabel.FIXTURE,
                         "人工编写的南京示例地点和近似区域，未现场核验；非实时来源。",
                         {"lat": lat, "lon": lon, "subject_lat":32.0621 if "cityscape" in brief.intent.categories else None,
                          "subject_lon":118.7780 if "cityscape" in brief.intent.categories else None}, kind="fixture")
        community = ledger.add(f"community-{sid}", "社区发现流程 · 合成样例", TruthLabel.FIXTURE,
                               composition + " 这是合成的构图 Claim，不对应真实帖子。", kind="fixture")
        access = ledger.add(f"access-{sid}", "官方复核流程 · 合成样例", TruthLabel.FIXTURE,
                            "当日开放、预约、夜游、脚架政策未知，不作已开放承诺。", kind="fixture")
        position = Position(lat=lat, lon=lon, evidence_ids=ids)
        claim = SourceClaim(id=f"claim-{sid}", source_id=ledger.evidence[-2].source_id, subject_id=sid,
                            kind="composition", statement=composition, label=TruthLabel.FIXTURE,
                            evidence_ids=community)
        claims.append(claim)
        target = Position(lat=32.0621, lon=118.7780, evidence_ids=ids) if "cityscape" in brief.intent.categories else None
        spots.append(PhotoSpot(id=sid, place=PlaceEntity(id=sid, name=name, position=position),
            name=name, camera=position, entrance=None,
            subjects=[Subject(name="紫峰大厦方向（示意）" if target else subject, position=target)],
            genres=brief.intent.categories, composition=composition, access_evidence_ids=access,
            risks=["请勿进入机动车道、翻越护栏或进入非公开区域。"], claim_ids=[claim.id]))
    return spots, claims


def seed_conditions(brief, ledger):
    values = {"temperature_c": 24, "precipitation_mm": 0, "wind_kmh": 8,
              "cloud_pct": 35, "visibility_m": 20000, "weather_code": 2, "aqi": 42}
    ids = ledger.add("weather-fixture", "离线天气 Fixture", TruthLabel.FIXTURE,
                     "固定晴间多云天气，仅用于演示，不是预报。", values, kind="fixture")
    start = datetime.combine(brief.travel_date, datetime.min.time(), ZoneInfo(brief.timezone)).astimezone(UTC)
    return [HourlyCondition(at=start + timedelta(hours=h), label=TruthLabel.FIXTURE,
                            evidence_ids=ids, **values) for h in range(24)]


def seed_routes(spots, ledger):
    routes = []
    for i, a in enumerate(spots):
        for j, b in enumerate(spots):
            if j <= i:
                continue
            distance, duration = 420 * (j - i), 7 * (j - i)
            ids = ledger.add(f"route-{a.id}-{b.id}", "离线路线 Fixture", TruthLabel.FIXTURE,
                             "演示路线时长与距离；虚线仅连接区域，不可用于导航。",
                             {"distance_m": distance, "duration_min": duration}, kind="fixture")
            routes.append(RouteLeg(from_id=a.id, to_id=b.id, distance_m=distance, duration_min=duration,
                geometry=[[a.camera.lon, a.camera.lat], [b.camera.lon, b.camera.lat]],
                label=TruthLabel.FIXTURE, evidence_ids=ids, note="区域间演示连接线 · 非导航路线"))
    return routes
