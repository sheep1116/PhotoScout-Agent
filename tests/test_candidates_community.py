from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.community.base import photographic_info
from backend.app.community.bilibili import BilibiliAdapter
from backend.app.community.service import CommunityService
from backend.app.engine import Ledger, notebook
from backend.app.fixtures import seed_conditions, seed_spots
from backend.app.graph import run_graph
from backend.app.main import create_app
from backend.app.models import ShotPlan, TripBrief
from backend.app.providers import Providers
from backend.app.recommendations import build_recommendations, window


def recommend(brief, edit=None):
    brief = notebook(brief).brief
    ledger = Ledger()
    spots, claims = seed_spots(brief, ledger)
    if edit:
        edit(spots)
    weather = seed_conditions(brief, ledger)
    return build_recommendations("candidates", brief, spots, claims, {s.id: weather for s in spots}, ledger, [])


def test_candidates_do_not_need_routes_or_walking_budget(brief):
    brief.mode = "live"
    brief.intent.preferences.max_walk_km = 0
    plan = recommend(brief)
    assert len(plan.tasks) == len(plan.spots) == 4
    assert len({t.spot_id for t in plan.tasks}) == 4
    assert not plan.routes and plan.presentation == "candidates"
    assert len({(t.start, t.end) for t in plan.tasks}) == 1
    assert ShotPlan.model_validate_json(plan.model_dump_json())


def test_daylight_uses_local_sunrise_and_blue_hour_is_not_missed(brief):
    from zoneinfo import ZoneInfo
    brief = notebook(brief).brief
    brief.intent.light = "daylight"
    plan = recommend(brief)
    assert len(plan.tasks) == 4
    assert plan.solar.sunrise < plan.solar.sunset
    assert plan.solar.sunrise.astimezone(ZoneInfo(brief.timezone)).date() == brief.travel_date
    brief.intent.light = "blue_hour"
    assert all(t.recommended_light == "blue_hour" for t in recommend(brief).tasks)


def test_transport_preferences_never_remove_candidates(brief):
    brief.intent.preferences.avoid_tickets = True
    brief.intent.preferences.low_crowd = True
    plan = recommend(brief, lambda spots: [setattr(s, "ticket_required", True) for s in spots])
    assert len(plan.tasks) == 4
    assert all(any("门票" in line for line in t.travel_advice) for t in plan.tasks)


@pytest.mark.parametrize("field,value", [("access", "CLOSED")])
def test_safety_and_access_still_gate(brief, field, value):
    plan = recommend(brief, lambda spots: setattr(spots[0], field, value))
    assert len(plan.tasks) == 3 and plan.excluded


def test_distinct_candidate_windows_and_origin_distance(brief):
    brief.origin_lat, brief.origin_lon = 32.05, 118.84
    def edit(spots):
        spots[0].open_from = datetime(2026, 10, 3, 9, tzinfo=UTC)
        spots[1].open_until = datetime(2026, 10, 3, 8, tzinfo=UTC)
    plan = recommend(brief, edit)
    by_spot = {t.spot_id: t for t in plan.tasks}
    assert by_spot[plan.spots[0].id].start >= datetime(2026, 10, 3, 9, tzinfo=UTC)
    assert by_spot[plan.spots[1].id].end <= datetime(2026, 10, 3, 8, tzinfo=UTC)
    assert all(t.distance_km is not None for t in plan.tasks)


async def test_cross_midnight_graph(brief, settings):
    brief.start_local = datetime.strptime("23:30", "%H:%M").time()
    brief.end_local = datetime.strptime("02:00", "%H:%M").time()
    events = []
    async def emit(stage, message):
        events.append(stage)
    plan = await run_graph("midnight", brief, settings, emit)
    begin, finish = window(brief)
    assert finish-begin == timedelta(hours=2.5)
    assert plan.tasks and all(begin <= t.start < t.end <= finish for t in plan.tasks)
    assert all(t.recommended_light == "night" for t in plan.tasks)


def test_cross_midnight_derives_end_date(brief):
    data = brief.model_dump()
    data.update(start_local="23:30", end_local="02:00")
    cross_midnight = TripBrief.model_validate(data)
    assert cross_midnight.end_date == brief.travel_date + timedelta(days=1)
    data.update(start_local="18:00", end_local="21:00", end_date=brief.travel_date+timedelta(days=1))
    same_day = TripBrief.model_validate(data)
    assert same_day.end_date == brief.travel_date


@pytest.mark.parametrize("day,start", [("2026-03-08", "02:30"), ("2026-11-01", "01:30")])
def test_dst_gap_and_fold_are_not_silently_misinterpreted(day, start):
    with pytest.raises(ValidationError, match="夏令时"):
        TripBrief(travel_date=day, start_local=start, end_local="05:00", timezone="America/New_York")


def test_photographic_metadata_only_contains_actual_words():
    result = photographic_info("南京玄武湖 85mm 长焦压缩 日落倒影")
    assert result["focal_lengths"] == ["85mm"]
    assert result["time_light"] == ["日落"]
    assert "对称" not in result["composition"]


async def test_bilibili_public_metadata_retains_date_and_evidence(settings, brief, respx_mock):
    settings.enable_community = True
    respx_mock.get("https://api.bilibili.com/x/web-interface/search/type").respond(200, json={"code": 0, "data": {
        "result": [{"bvid": "BV1234567890", "title": "南京玄武湖机位", "description": "<b>85mm</b> 日落 倒影", "pubdate": 1700000000}]}})
    provider = Providers(settings)
    service = CommunityService()
    ledger, warnings = Ledger(), []
    try:
        posts = await service.discover(brief, provider)
        await service.enrich_indexed([], provider, ledger, warnings)
    finally:
        await provider.client.aclose()
    assert posts[0].published_at.tzinfo is not None
    assert ledger.sources[0].platform == "bilibili"
    assert ledger.sources[0].published_at == posts[0].published_at
    assert ledger.evidence[0].label == "REPORTED"
    assert ledger.evidence[0].values["photographic_info"]["focal_lengths"] == ["85mm"]
    assert service.sources()[0]["index"] == 1001


@pytest.mark.parametrize("response", [httpx.Response(412), httpx.Response(200, json={"code": -352}),
                                     httpx.Response(200, text="CAPTCHA"), httpx.Response(401)])
async def test_platform_restriction_isolated(settings, brief, respx_mock, response):
    settings.enable_community = True
    provider = Providers(settings)
    provider.cache.items.clear()
    respx_mock.get("https://api.bilibili.com/x/web-interface/search/type").mock(return_value=response)
    service = CommunityService()
    try:
        assert await service.discover(brief, provider) == []
    finally:
        await provider.client.aclose()
    assert service.status["bilibili"] == "restricted_or_unavailable"
    assert service.status["xiaohongshu"] == service.status["douyin"] == "index_only"


async def test_bilibili_url_allowlist_never_fetches_untrusted_hosts():
    client = AsyncMock()
    adapter = BilibiliAdapter()
    assert await adapter.read("https://bilibili.com.evil.test/video/BV1234567890", client) is None
    assert await adapter.read("https://www.bilibili.com/video/../../private", client) is None
    client.get.assert_not_called()


async def test_bilibili_metadata_to_mapped_candidate_pipeline(settings, brief, respx_mock, monkeypatch):
    from pydantic import SecretStr
    settings.enable_community = True
    settings.amap_web_service_key = SecretStr("community-contract-secret")
    brief.mode = "live"
    brief.destination = "南京玄武湖"
    brief.travel_date = (datetime.now(UTC)+timedelta(days=40)).date()
    metadata = {"bvid": "BV1234567890", "title": "南京玄武湖玄武门机位", "desc": "85mm 日落 倒影",
                "pic": "http://i0.hdslb.com/bfs/archive/sample.jpg", "owner": {"name": "摄影作者"}, "pubdate": 1700000000}
    respx_mock.get("https://api.bilibili.com/x/web-interface/search/type").respond(200, json={"code": 0, "data": {"result": [metadata]}})
    respx_mock.get("https://api.bilibili.com/x/web-interface/view").respond(200, json={"code": 0, "data": metadata})
    respx_mock.get(settings.amap_base_url+"/v3/geocode/geo").respond(200, json={"status": "1", "geocodes": [{"city": "南京市", "location": "118.8,32.06"}]})
    respx_mock.get(settings.amap_base_url+"/v3/place/text").respond(200, json={"status": "1", "pois": [{"id": "gate", "name": "玄武门", "location": "118.8,32.06"}]})
    provider = Providers(settings)
    provider.cache.items.clear()
    async def extraction(_brief, _purpose):
        # Model contract stub: its only citation comes from the actual adapter output.
        assert provider.community.sources()[0]["photographic_info"]["focal_lengths"] == ["85mm"]
        return {"retrieved_at": datetime.now(UTC).isoformat(), "sources": provider.community.sources(),
                "candidates": [{"name": "玄武门", "camera_poi": "玄武门", "place_name": "玄武湖",
                                "composition": "日落倒影", "source_indices": [1001]}]}
    monkeypatch.setattr(provider, "search", extraction)
    plan = await run_graph("bili-pipeline", brief, settings, AsyncMock(), provider=provider)
    assert len(plan.tasks) == 1 and plan.spots[0].camera.lat is not None
    assert plan.spots[0].access == "UNKNOWN"
    metadata_claim = next(c for c in plan.claims if c.source_id.startswith("community-"))
    assert metadata_claim.id in plan.spots[0].claim_ids
    record = next(e for e in plan.evidence if e.id in metadata_claim.evidence_ids)
    assert record.values["photographic_info"]["focal_lengths"] == ["85mm"]
    assert record.values["published_at"] is not None
    sample = plan.spots[0].photo_references[0]
    assert sample.provider == "community" and sample.relation == "source"
    assert sample.author == "摄影作者" and str(sample.image_url).startswith("https://i0.hdslb.com/")


def test_location_failure_is_nonfatal_and_never_creates_research(settings):
    with TestClient(create_app(settings)) as client:
        result = client.get("/v1/location/ip")
        assert result.status_code == 200 and result.json()["city"] is None
        assert client.get("/v1/plans").json() == []
        assert client.post("/v1/location/reverse", json={"lat": 100, "lon": 120}).status_code == 422


def test_location_reverse_keeps_keys_server_side(settings, respx_mock):
    from pydantic import SecretStr
    settings.amap_web_service_key = SecretStr("location-test-secret")
    respx_mock.get(settings.amap_base_url + "/v3/geocode/regeo").respond(200, json={"status": "1", "regeocode": {
        "addressComponent": {"city": "南京市"}}})
    with TestClient(create_app(settings)) as client:
        result = client.post("/v1/location/reverse", json={"lat": 32.05, "lon": 118.84})
        assert result.json()["city"] == "南京市"
        assert "location-test-secret" not in result.text
