"""Public domain contracts. No provider response objects cross this boundary."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


def now() -> datetime:
    return datetime.now(UTC)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @field_validator("*", mode="after")
    @classmethod
    def aware_timestamps(cls, value):
        if isinstance(value, datetime) and value.tzinfo is None:
            raise ValueError("时间戳必须包含时区")
        return value


class TruthLabel(StrEnum):
    VERIFIED = "VERIFIED"
    REPORTED = "REPORTED"
    CALCULATED = "CALCULATED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"
    STALE = "STALE"
    CONFLICT = "CONFLICT"
    FIXTURE = "FIXTURE"
    USER_CONFIRMED = "USER_CONFIRMED"


class LocationPrecision(StrEnum):
    EXACT_VERIFIED = "EXACT_VERIFIED"
    MAP_POINT = "MAP_POINT"
    AREA = "AREA"
    APPROXIMATE = "APPROXIMATE"
    UNKNOWN = "UNKNOWN"


class Lens(Model):
    name: str = Field(max_length=100)
    min_mm: float = Field(ge=1, le=2000)
    max_mm: float = Field(ge=1, le=2000)
    max_aperture: float = Field(default=4, ge=0.7, le=32)

    @model_validator(mode="after")
    def ordered(self):
        if self.max_mm < self.min_mm:
            raise ValueError("镜头焦段范围颠倒")
        return self


Category = Literal["portrait", "cityscape", "landscape", "humanities", "architecture", "nature"]


class EquipmentIntent(Model):
    lenses: list[Lens] = Field(default_factory=list, max_length=8)
    sensor: Literal["full_frame", "aps_c", "m43", "phone"] = "full_frame"
    tripod: bool = False


class RecommendationPreferences(Model):
    max_walk_km: float | None = Field(default=None, ge=0, le=100)
    avoid_tickets: bool = False
    low_crowd: bool = False
    step_free: bool = False
    strict: list[Literal["free", "step_free", "low_crowd", "walking"]] = Field(default_factory=list)


class DestinationLocation(Model):
    id: str
    poi_id: str | None = None
    adcode: str
    name: str
    city: str
    address: str = ""
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    verification_token: str = ""


class PhotographyIntent(Model):
    categories: list[Category] = Field(default_factory=list, max_length=6)
    recommendation_mode: Literal["best", "multiple"] = "best"
    subjects: list[str] = Field(default_factory=list, max_length=8)
    styles: list[str] = Field(default_factory=list, max_length=8)
    light: Literal["any", "daylight", "sunrise", "golden_hour", "blue_hour", "night"] = "any"
    equipment: EquipmentIntent | None = None
    preferences: RecommendationPreferences = Field(default_factory=RecommendationPreferences)
    other_requirements: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="before")
    @classmethod
    def migrate_old_intent(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        value.pop("constraints", None)
        mobility = value.pop("mobility", None)
        if mobility == "step_free" and "preferences" not in value:
            value["preferences"] = {"step_free": True}
        return value

    @field_validator("categories")
    @classmethod
    def equal_categories(cls, values):
        return sorted(set(values))

    @field_validator("subjects", "styles")
    @classmethod
    def bounded_tags(cls, values):
        if any(not value.strip() or len(value) > 40 for value in values):
            raise ValueError("意图标签应为 1–40 个字符")
        return list(dict.fromkeys(v.strip() for v in values))


class ReverseContext(Model):
    analysis_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    spot_id: str = Field(min_length=1, max_length=150)


class ReferenceSearch(Model):
    region_hint: str = Field(default='',max_length=150)
    notes: str = Field(default='',max_length=1500)
    data_mode: Literal['live','mock'] = 'live'


class TripBrief(Model):
    reverse_context: ReverseContext | None = None
    text: str = Field(default="", max_length=1500)
    destination: str = Field(default="", max_length=100)
    travel_date: date | None = None
    end_date: date | None = None
    origin_lat: float | None = Field(default=None, ge=-90, le=90)
    origin_lon: float | None = Field(default=None, ge=-180, le=180)
    start_local: time | None = None
    end_local: time | None = None
    timezone: str = "Asia/Shanghai"
    intent: PhotographyIntent = Field(default_factory=PhotographyIntent)
    location: DestinationLocation | None = None
    edited_fields: list[str] = Field(default_factory=list, max_length=20)
    auto_time_fields: list[Literal["start_local", "end_local", "end_date"]] = Field(default_factory=list)
    lenses: list[Lens] = Field(default_factory=list, max_length=8)
    sensor: Literal["full_frame", "aps_c", "m43", "phone"] = "full_frame"
    tripod: bool = False
    mode: Literal["mock", "live"] = "mock"

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_fields(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        # Read historical JSON without keeping obsolete fields in the active API.
        old_genre = data.pop("genre", None)
        for key in ("profile", "max_walk_km", "accept_tickets", "crowd_tolerance"):
            data.pop(key, None)
        intent = data.get("intent")
        if isinstance(intent, PhotographyIntent):
            intent = intent.model_dump()
        if not intent:
            intent = {"categories": [old_genre]} if old_genre else {}
        equipment = intent.get("equipment")
        if isinstance(equipment, dict):
            for key, item in equipment.items():
                data.setdefault(key, item)
        data["intent"] = intent
        return data

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError("未知时区") from exc
        return value

    @model_validator(mode="after")
    def window(self):
        # The UI only asks for one date and a time range. An earlier end time
        # means the following day; callers cannot leave a stale end date behind.
        if self.travel_date:
            self.end_date = self.travel_date + timedelta(
                days=1 if self.start_local and self.end_local and self.end_local < self.start_local else 0
            )
        else:
            self.end_date = None
        if (self.origin_lat is None) != (self.origin_lon is None):
            raise ValueError("起点经纬度须同时提供")
        for day, clock in ((self.travel_date, self.start_local), (self.end_date or self.travel_date, self.end_local)):
            if day and clock:
                local = datetime.combine(day, clock)
                zone = ZoneInfo(self.timezone)
                first = local.replace(tzinfo=zone, fold=0)
                if first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != local:
                    raise ValueError("所选时间因夏令时跳时不存在，请选择其他时间")
                if first.utcoffset() != local.replace(tzinfo=zone, fold=1).utcoffset():
                    raise ValueError("所选时间因夏令时回拨有歧义，请选择回拨时段之外的时间")
        return self


class TripNotebook(Model):
    brief: TripBrief
    missing_fields: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    recognized: list[str] = Field(default_factory=list)
    parsed_fields: list[str] = Field(default_factory=list)
    parser: str = "defaults"
    location_choices: list[DestinationLocation] = Field(default_factory=list)
    location_status: str = "not_requested"


class WebSource(Model):
    id: str
    url: HttpUrl | None = None
    title: str
    publisher: str
    kind: Literal["official", "community", "media", "search", "tool", "fixture", "user"]
    platform: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=now)
    note: str = ""


class Evidence(Model):
    id: str
    source_id: str
    label: TruthLabel
    statement: str
    observed_at: datetime = Field(default_factory=now)
    valid_until: datetime | None = None
    values: dict[str, Any] = Field(default_factory=dict)


class SourceClaim(Model):
    id: str
    source_id: str
    subject_id: str
    kind: Literal["viewpoint", "access", "composition", "safety", "photo"]
    statement: str
    label: TruthLabel = TruthLabel.REPORTED
    evidence_ids: list[str]
    valid_until: datetime | None = None


class LocationAnchor(Model):
    display_name: str = Field(max_length=120)
    map_anchor: str = Field(max_length=120)


class AgentCandidate(Model):
    """A discovery lead is preserved even when it cannot yet become a map spot."""
    id: str
    name: str = Field(max_length=100)
    camera_poi: str = Field(default="", max_length=100)
    place_name: str = Field(default="", max_length=100)
    camera_instruction: str = Field(default="", max_length=400)
    subjects: list[str] = Field(default_factory=list, max_length=8)
    shooting_direction: str = Field(default="", max_length=200)
    composition: str = Field(default="", max_length=500)
    recommended_time: str = Field(default="", max_length=300)
    time_judgment: str = Field(default="", max_length=500)
    equipment_advice: str = Field(default="", max_length=500)
    settings_advice: dict[str, str] = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list, max_length=12)
    confidence: Literal["low", "medium", "high"] = "low"
    verification_status: Literal["mapped", "area", "map_only", "unlocated", "rejected"] = "unlocated"
    verification_note: str = Field(default="尚未完成地图与来源核验。", max_length=500)
    mapped_spot_id: str | None = None
    camera_location: LocationAnchor | None = None
    subject_locations: list[LocationAnchor] = Field(default_factory=list, max_length=8)
    rank: int = Field(default=1, ge=1, le=12)
    selection_reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def location_protocol(self):
        if self.camera_location is None:
            self.camera_location = LocationAnchor(display_name=self.name,
                map_anchor=self.camera_poi or self.name)
        if not self.subject_locations:
            self.subject_locations = [LocationAnchor(display_name=name, map_anchor=name) for name in self.subjects]
        return self


class AgentAnswer(Model):
    """The user-facing Agent answer, kept separately from verified spatial entities."""
    summaries: list[str] = Field(default_factory=list, max_length=4)
    candidates: list[AgentCandidate] = Field(default_factory=list, max_length=12)
    source_ids: list[str] = Field(default_factory=list, max_length=24)


class Position(Model):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    precision: LocationPrecision = LocationPrecision.AREA
    crs: Literal["WGS84"] = "WGS84"
    evidence_ids: list[str] = Field(min_length=1)


class PlaceEntity(Model):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    timezone: str = "Asia/Shanghai"
    position: Position


class Subject(Model):
    name: str
    position: Position | None = None


class PhotoReference(Model):
    id: str
    provider: Literal["amap", "wikimedia", "flickr", "community"]
    image_url: HttpUrl
    source_url: HttpUrl
    source_id: str
    title: str = Field(max_length=300)
    author: str = Field(default="未提供", max_length=300)
    license: str = Field(default="版权归原作者；仅供参考，转载需另行授权", max_length=300)
    retrieved_at: datetime = Field(default_factory=now)
    captured_at: str | None = None
    relation: Literal["poi", "nearby", "source"] = "poi"
    # API geotags are not verified camera positions.
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    exif: dict[str, str] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(min_length=1)


class PhotoSpot(Model):
    id: str
    place: PlaceEntity
    name: str
    camera: Position
    viewpoint_status: Literal["area_candidate", "mapped_viewpoint"] = "area_candidate"
    camera_instruction: str = "精确站位待现场确认"
    photo_references: list[PhotoReference] = Field(default_factory=list, max_length=12)
    entrance: Position | None = None
    subjects: list[Subject]
    genres: list[str]
    composition: str
    access: Literal["OPEN", "CLOSED", "UNKNOWN", "CONFLICT"] = "UNKNOWN"
    access_evidence_ids: list[str]
    open_from: datetime | None = None
    open_until: datetime | None = None
    ticket_required: bool | None = None
    unsafe: bool = False
    popularity: str = "UNVERIFIED"
    tripod_allowed: bool | None = None
    step_free: bool | None = None
    risks: list[str]
    claim_ids: list[str]


class HourlyCondition(Model):
    at: datetime
    temperature_c: float | None = None
    precipitation_mm: float | None = None
    wind_kmh: float | None = None
    cloud_pct: float | None = None
    visibility_m: float | None = None
    weather_code: int | None = None
    aqi: float | None = None
    label: TruthLabel
    evidence_ids: list[str]


class SolarWindow(Model):
    sunrise: datetime | None = None
    sunset: datetime | None = None
    golden_start: datetime | None = None
    blue_start: datetime | None = None
    blue_end: datetime | None = None
    evidence_ids: list[str]


class CrowdSignal(Model):
    level: Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"] = "UNKNOWN"
    source_type: str = "UNKNOWN"
    spatial_scope: str
    observed_at: datetime | None = None
    valid_until: datetime | None = None
    label: TruthLabel = TruthLabel.UNKNOWN
    evidence_ids: list[str]


class RouteLeg(Model):
    from_id: str
    to_id: str
    distance_m: float | None = Field(default=None, ge=0)
    duration_min: float | None = Field(default=None, ge=0, le=1440)
    geometry: list[list[float]] = Field(default_factory=list)
    label: TruthLabel
    evidence_ids: list[str]
    note: str


class ScoreBreakdown(Model):
    suitability: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    components: dict[str, float]
    weights: dict[str, float]
    adjustments: dict[str, float] = Field(default_factory=dict)
    evidence_ids: list[str]


class CameraAdvice(Model):
    lens: str
    focal_mm: float
    equivalent_mm: float
    aperture: float
    shutter_seconds: float
    iso: int
    adjustment: str
    evidence_ids: list[str]


class ShotTask(Model):
    alerts: list[str] = Field(default_factory=list)
    id: str
    spot_id: str
    title: str
    start: datetime
    end: datetime
    status: Literal["READY", "TENTATIVE", "CANCELLED"]
    composition: str
    camera: CameraAdvice
    weather: HourlyCondition
    crowd: CrowdSignal
    score: ScoreBreakdown
    solar_azimuth_deg: float
    target_bearing_deg: float | None = None
    subject_bearings_deg: dict[str, float] = Field(default_factory=dict)
    subject_distances_km: dict[str, float] = Field(default_factory=dict)
    subject_separation_deg: float | None = None
    field_of_view_deg: float | None = None
    framing_assessment: str = ""
    risks: list[str]
    alternative: str
    reasons: list[str] = Field(default_factory=list)
    travel_advice: list[str] = Field(default_factory=list)
    distance_km: float | None = None
    recommended_light: str = "any"
    evidence_ids: list[str]


class ShotPlan(Model):
    recreation: dict[str, Any] | None = None
    presentation: Literal["itinerary", "candidates"] = "itinerary"
    id: str
    version: int = 1
    brief: TripBrief
    created_at: datetime = Field(default_factory=now)
    status: Literal["DRAFT", "READY"] = "DRAFT"
    agent_answer: AgentAnswer = Field(default_factory=AgentAnswer)
    spots: list[PhotoSpot]
    tasks: list[ShotTask]
    routes: list[RouteLeg]
    solar: SolarWindow
    sources: list[WebSource]
    claims: list[SourceClaim]
    evidence: list[Evidence]
    warnings: list[str]
    excluded: list[dict[str, str]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def read_legacy_reference_plan(cls, value):
        if isinstance(value, dict) and isinstance(value.get('brief'), dict):
            value = dict(value)
            brief = dict(value['brief'])
            if isinstance(brief.get('reverse_context'), dict):
                context = dict(brief['reverse_context'])
                context.pop('days', None)
                brief['reverse_context'] = context
            value['brief'] = brief
        return value

    @model_validator(mode="after")
    def integrity(self):
        source_ids = {s.id for s in self.sources}
        evidence_ids = {e.id for e in self.evidence}
        spot_ids = {s.id for s in self.spots}
        if len(evidence_ids) != len(self.evidence):
            raise ValueError("重复证据 ID")
        if any(e.source_id not in source_ids for e in self.evidence):
            raise ValueError("证据来源缺失")

        photos = {}
        for spot in self.spots:
            for photo in spot.photo_references:
                if photo.source_id not in source_ids:
                    raise ValueError("图片来源缺失")
                if any(next(e for e in self.evidence if e.id == eid).source_id != photo.source_id
                       for eid in photo.evidence_ids if eid in evidence_ids):
                    raise ValueError("图片证据来源不一致")
                if photo.id in photos and photos[photo.id] != str(photo.image_url):
                    raise ValueError("图片 ID 冲突")
                photos[photo.id] = str(photo.image_url)

        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key.endswith("evidence_ids"):
                        if not item or not set(item) <= evidence_ids:
                            raise ValueError("证据绑定缺失")
                    else:
                        walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(self.model_dump())
        if self.presentation == "candidates":
            if len({t.spot_id for t in self.tasks}) != len(self.tasks):
                raise ValueError("每个机位只能有一张候选卡片")
            if self.routes:
                raise ValueError("候选结果不应包含行程路线")
            if self.brief.travel_date and self.brief.start_local and self.brief.end_local:
                zone = ZoneInfo(self.brief.timezone)
                start = datetime.combine(self.brief.travel_date, self.brief.start_local, zone)
                end = datetime.combine(self.brief.end_date or self.brief.travel_date, self.brief.end_local, zone)
                if any(t.start < start or t.end > end for t in self.tasks):
                    raise ValueError("候选窗口超出用户可用时间")
        previous = None
        for task in self.tasks:
            if task.spot_id not in spot_ids:
                raise ValueError("机位缺失")
            if task.start.tzinfo is None or task.end.tzinfo is None or task.start >= task.end:
                raise ValueError("任务时间无效")
            if self.presentation == "itinerary" and previous and task.start < previous:
                raise ValueError("任务时间重叠")
            previous = task.end
        return self


class FieldDiff(Model):
    path: str
    before: Any
    after: Any


class PlanChangeProposal(Model):
    id: str
    plan_id: str
    base_version: int
    reason: str
    status: Literal["PENDING", "APPROVED", "REJECTED"] = "PENDING"
    diff: list[FieldDiff]
    proposed: ShotPlan
    created_at: datetime = Field(default_factory=now)


class PlanVersion(Model):
    plan_id: str
    version: int
    reason: str
    created_at: datetime = Field(default_factory=now)
    plan: ShotPlan
