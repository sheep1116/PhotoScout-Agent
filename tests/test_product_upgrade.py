import asyncio
import socket
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from backend.app.discovery import AMapPhotos, DiscoveryHub, FlickrPhotos, WikimediaPhotos, image_url
from backend.app.engine import Ledger, build_plan, camera_advice, notebook
from backend.app.fixtures import seed_conditions, seed_routes, seed_spots
from backend.app.main import create_app
from backend.app.media import fetch_image
from backend.app.models import PhotographyIntent, ShotPlan
from backend.app.providers import DiscoveredSpot, Providers, source_kind
from backend.app.repository import Repository


@pytest.mark.parametrize("category", ["landscape", "portrait", "humanities", "architecture", "nature", "cityscape"])
async def test_every_category_uses_same_graph(category, brief, settings):
    from backend.app.graph import run_graph
    brief.intent = PhotographyIntent(categories=[category], styles=["极简"], subjects=["建筑"])
    stages = []
    async def emit(stage, message):
        stages.append(stage)
    plan = await run_graph("intent-" + category, brief, settings, emit)
    assert plan.tasks
    assert plan.brief.intent.categories == [category]
    assert plan.brief.intent.equipment.lenses == brief.lenses
    assert plan.brief.intent.preferences.max_walk_km is None
    assert stages == ["parse", "discover", "evidence", "verify", "conditions", "schedule", "validate"]


def test_daylight_architecture_does_not_use_night_iso(brief):
    brief.intent.categories = ["architecture"]
    assert camera_advice(brief, 0, Ledger()).iso == 200


def test_step_free_does_not_recommend_unverified_access(brief):
    brief.intent = PhotographyIntent(categories=["landscape"], mobility="step_free")
    brief = notebook(brief).brief
    ledger = Ledger()
    spots, claims = seed_spots(brief, ledger)
    plan = build_plan("access", brief, spots, claims, seed_conditions(brief, ledger),
                      seed_routes(spots, ledger), ledger, [])
    assert plan.tasks and not plan.excluded
    assert any("无台阶" in a for t in plan.tasks for a in t.alerts)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/a", "http://169.254.169.254/latest/meta-data", "https://localhost/a",
    "https://upload.wikimedia.org.evil.test/a", "https://evil.test/upload.wikimedia.org/a",
    "https://user:pass@upload.wikimedia.org/a", "https://upload.wikimedia.org:8443/a",
    "file:///etc/passwd", "data:image/svg+xml,test", "https://store.is.autonavi.com/a?key=private",
])
def test_proxy_url_allowlist(url):
    assert image_url(url) is None


def test_real_api_photos_only_and_missing_photo_fallback():
    ledger = Ledger()
    poi = {"id": "B1", "name": "测试景点", "photos": [
        {"url": "http://store.is.autonavi.com/showpic/real.jpg", "title": "真实 API 图"},
        {"url": "https://evil.test/generated.jpg"}, {"url": "javascript:alert(1)"}]}
    photos = AMapPhotos.from_poi(poi, ledger)
    assert len(photos) == 1
    assert str(photos[0].image_url).startswith("https://store.is.autonavi.com/")
    assert photos[0].source_id == ledger.evidence[0].source_id
    assert AMapPhotos.from_poi({"id": "B2", "name": "无图"}, ledger) == []
    with pytest.raises(ValidationError):
        DiscoveredSpot(name="站位", composition="线索", source_indices=[1], image_url="https://example.com/fake.jpg")


@pytest.mark.parametrize("domain", ["xiaohongshu.com", "douyin.com", "bilibili.com", "weibo.com", "weibo.cn"])
def test_community_never_official(domain):
    assert source_kind(f"https://www.{domain}/post") == "community"
    assert source_kind(f"https://{domain}.evil.test/post") == "search"


async def test_wikimedia_normalizes_license_and_nearby(settings, plan, respx_mock):
    respx_mock.get("https://commons.wikimedia.org/w/api.php").respond(200, json={"query": {"pages": {"1": {
        "title": "File:Lake.jpg", "coordinates": [{"lat": 32.05, "lon": 118.84}], "imageinfo": [{
        "mime": "image/jpeg", "thumburl": "https://upload.wikimedia.org/wikipedia/commons/a/a1/Lake.jpg",
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Lake.jpg",
        "extmetadata": {"Artist": {"value": "<a href='x'>Alice</a>"}, "LicenseShortName": {"value": "CC BY-SA 4.0"}}
    }]}}}})
    provider, ledger = Providers(settings), Ledger()
    try:
        photos = await WikimediaPhotos().discover(plan.spots[0], ledger, provider)
    finally:
        await provider.client.aclose()
    assert photos[0].author == "Alice"
    assert photos[0].relation == "nearby"
    assert photos[0].license == "CC BY-SA 4.0"
    assert photos[0].latitude == 32.05


async def test_flickr_gps_exif_and_no_key_disclosure(settings, plan, respx_mock):
    settings.flickr_api_key = SecretStr("contract-flickr-secret")
    def reply(request):
        if request.url.params["method"] == "flickr.photos.search":
            return httpx.Response(200, json={"stat": "ok", "photos": {"photo": [{"id": "123", "owner": "456@N00",
                "ownername": "Photographer", "license": "4", "title": "湖面", "latitude": "32.05", "longitude": "118.84",
                "url_z": "https://live.staticflickr.com/1/123_test_z.jpg", "datetaken": "2025-10-03 15:00:00"}]}})
        return httpx.Response(200, json={"stat": "ok", "photo": {"exif": [
            {"tag": "FNumber", "label": "Aperture", "raw": {"_content": "8"}},
            {"tag": "SerialNumber", "label": "Private serial", "raw": {"_content": "DO-NOT-SHOW"}}]}})
    respx_mock.get("https://www.flickr.com/services/rest/").mock(side_effect=reply)
    provider, ledger = Providers(settings), Ledger()
    try:
        photos = await FlickrPhotos().discover(plan.spots[0], ledger, provider)
    finally:
        await provider.client.aclose()
    assert photos[0].exif == {"Aperture": "8"}
    assert photos[0].license == "CC BY 2.0"
    assert "contract-flickr-secret" not in photos[0].model_dump_json()


async def test_optional_provider_failure_preserves_plan(settings, plan, respx_mock):
    settings.enable_external_photos = True
    respx_mock.get("https://commons.wikimedia.org/w/api.php").respond(503)
    provider, ledger, warnings = Providers(settings), Ledger(), []
    try:
        await DiscoveryHub().enrich(plan.spots, ledger, provider, warnings)
    finally:
        await provider.client.aclose()
    assert any("wikimedia" in w and "不可用" in w for w in warnings)
    assert any("Flickr" in w and "未配置" in w for w in warnings)


async def test_private_dns_is_blocked_before_fetch(monkeypatch):
    resolver = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    with pytest.raises(ValueError, match="ADDRESS_NOT_PUBLIC"):
        await fetch_image("https://upload.wikimedia.org/a.jpg")


@pytest.mark.parametrize("status,mime,body,accepted", [
    (200, "image/jpeg", b"\xff\xd8\xfftest", True),
    (302, "image/jpeg", b"\xff\xd8\xff", False),
    (200, "image/svg+xml", b"<svg onload='alert(1)'/>", False),
    (200, "image/jpeg", b"<html>error</html>", False),
    (200, "image/jpeg", b"\xff\xd8\xff" + b"a" * (5 * 1024 * 1024), False),
], ids=["jpeg", "redirect", "svg", "mismatched", "oversized"])
async def test_proxy_content_boundaries(status, mime, body, accepted, monkeypatch, respx_mock):
    resolver = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    route = respx_mock.get("https://upload.wikimedia.org/a.jpg").respond(status, content=body,
        headers={"content-type": mime, "location": "http://127.0.0.1/private"})
    if accepted:
        assert await fetch_image("https://upload.wikimedia.org/a.jpg") == (body, mime)
    else:
        with pytest.raises(ValueError):
            await fetch_image("https://upload.wikimedia.org/a.jpg")
    assert route.call_count == 1


def test_stored_photo_endpoint_and_evidence_integrity(settings, plan, monkeypatch):
    ledger = Ledger()
    photos = AMapPhotos.from_poi({"id": "B1", "name": "湖", "photos": [
        {"url": "https://store.is.autonavi.com/a.jpg"}]}, ledger)
    plan.spots[0].photo_references = photos
    plan.sources.extend(ledger.sources)
    plan.evidence.extend(ledger.evidence)
    plan = ShotPlan.model_validate(plan.model_dump())
    repo = Repository(settings.database_url)
    repo.save(plan)
    fetch = AsyncMock(return_value=(b"\xff\xd8\xfftest", "image/jpeg"))
    monkeypatch.setattr("backend.app.media.fetch_image", fetch)
    with TestClient(create_app(settings, repo)) as client:
        assert client.get(f"/v1/plans/{plan.id}/photos/unknown").status_code == 404
        assert fetch.call_count == 0
        response = client.get(f"/v1/plans/{plan.id}/photos/{photos[0].id}")
        assert response.status_code == 200
        assert response.headers["x-content-type-options"] == "nosniff"
    plan.spots[0].photo_references[0].source_id = "made-up"
    with pytest.raises(ValidationError, match="图片来源缺失"):
        ShotPlan.model_validate(plan.model_dump())


async def test_camera_parent_subject_resolved_independently(settings, brief, respx_mock, monkeypatch):
    settings.enable_external_photos = False
    brief.destination = "南京"
    provider = Providers(settings)
    monkeypatch.setattr(provider, "geocode", AsyncMock(return_value={"city": "南京市"}))
    monkeypatch.setattr(provider, "search", AsyncMock(return_value={"retrieved_at": "2026-09-10T00:00:00Z",
        "sources": [{"index": 1, "title": "南京湖岸观景台拍摄经验", "url": "https://www.bilibili.com/video/test"}],
        "candidates": [{"name": "观景台", "place_name": "公园", "subject_poi": "塔楼", "subject": "塔楼",
                        "camera_instruction": "观景台公开步道", "composition": "以前景湖面衬托塔楼", "source_indices": [1]}]}))
    async def poi(name, city):
        return {"id": name, "name": name, "location": {"观景台": "118.84,32.05", "公园": "118.841,32.05", "塔楼": "118.85,32.051"}[name]}
    monkeypatch.setattr(provider, "poi", poi)
    ledger = Ledger()
    try:
        spots, claims = await provider.discover(brief, ledger, [])
    finally:
        await provider.client.aclose()
    assert len(spots) == 1
    assert spots[0].id != spots[0].place.id
    assert spots[0].subjects[0].position != spots[0].camera
    assert spots[0].viewpoint_status == "mapped_viewpoint"
    assert spots[0].access == "UNKNOWN"


def test_nested_intent_constraints_and_equipment_are_honored():
    from backend.app.models import TripBrief
    brief = TripBrief(destination="南京", intent={"categories": ["landscape", "architecture"],
        "equipment": {"sensor": "phone", "tripod": False},
        "preferences": {"max_walk_km": 1, "low_crowd": True}})
    assert brief.intent.preferences.max_walk_km == 1 and brief.sensor == "phone" and brief.intent.preferences.low_crowd
    assert brief.intent.categories == ["architecture", "landscape"]


async def test_unique_amap_sublandmark_suffix(settings, respx_mock):
    provider = Providers(settings)
    route = respx_mock.get(settings.amap_base_url + "/v3/place/text")
    route.respond(200, json={"status": "1", "pois": [{"id": "bridge", "name": "玄武湖景区-芳桥"},
        {"id": "pier", "name": "芳桥码头"}]})
    try:
        assert (await provider.poi("芳桥", "南京市"))["id"] == "bridge"
        route.respond(200, json={"status": "1", "pois": [{"id": "a", "name": "公园甲-芳桥"},
            {"id": "b", "name": "公园乙-芳桥"}]})
        from backend.app.providers import ProviderError
        with pytest.raises(ProviderError, match="AMBIGUOUS_POI"):
            await provider.poi("芳桥", "南京市")
    finally:
        await provider.client.aclose()


def test_combined_categories_affect_score(brief):
    from datetime import UTC, datetime

    from backend.app.engine import score, solar_windows
    ledger = Ledger()
    spots, _ = seed_spots(brief, ledger)
    brief.intent = PhotographyIntent(categories=["landscape", "architecture"])
    solar = solar_windows(brief, spots[0].camera, ledger)
    weather = seed_conditions(brief, ledger)[14]
    result = score(brief, weather, datetime(2026, 10, 3, 6, tzinfo=UTC), solar, ledger, 0)
    assert result.weights["构图"] == .25
    assert sum(result.weights.values()) == pytest.approx(1)
    assert "能见度" in result.components


async def test_locality_rejects_same_city_outside_requested_park(settings, brief, monkeypatch):
    brief.destination = "南京玄武湖"
    settings.enable_external_photos = False
    provider = Providers(settings)
    monkeypatch.setattr(provider, "geocode", AsyncMock(return_value={"city": "南京市"}))
    monkeypatch.setattr(provider, "search", AsyncMock(return_value={"retrieved_at": "2026-09-10T00:00:00Z",
        "sources": [{"index": 1, "title": "南京夫子庙拍摄指南", "url": "https://www.bilibili.com/video/test"}],
        "candidates": [{"name": "文德桥", "place_name": "夫子庙", "subject": "河流",
                        "composition": "倒影", "source_indices": [1]}]}))
    lookup = AsyncMock()
    monkeypatch.setattr(provider, "poi", lookup)
    try:
        spots, _ = await provider.discover(brief, Ledger(), [])
    finally:
        await provider.client.aclose()
    assert spots == [] and lookup.call_count == 0


def test_legacy_saved_plan_still_reads():
    from pathlib import Path
    legacy = Path(__file__).resolve().parents[1] / "docs/verification/plan-13309979295d4844bd2ff088d55bf865.json"
    result = ShotPlan.model_validate_json(legacy.read_text(encoding="utf-8"))
    assert result.tasks and all(not s.photo_references for s in result.spots)
