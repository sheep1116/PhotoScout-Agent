from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.app.engine import Ledger, camera_advice, fresh_crowd, gate, notebook, solar_windows
from backend.app.models import CrowdSignal, Lens, Position, ShotPlan, TripBrief
from backend.app.providers import canonical_url, gcj_to_wgs, source_kind, wgs_to_gcj


def test_complete_seed(plan):
    assert 3 <= len(plan.tasks) <= 5
    assert ShotPlan.model_validate_json(plan.model_dump_json())
    assert all(task.status == "TENTATIVE" for task in plan.tasks)
    assert plan.brief.mode == "mock"


def test_missing_date_questions(brief):
    brief.travel_date = None
    book = notebook(brief)
    assert "travel_date" in book.missing_fields
    assert book.questions


def test_natural_language_does_not_guess_relative_date():
    book = notebook(TripBrief(text="周六去南京拍夜景"))
    assert book.brief.genre == "cityscape"
    assert book.brief.destination == "南京"
    assert "travel_date" in book.missing_fields


@pytest.mark.parametrize("field,value", [("wind_kmh", 40), ("precipitation_mm", 7.5), ("weather_code", 95),
                                       ("weather_code", 96), ("weather_code", 99)])
def test_weather_gates(plan, field, value):
    task = plan.tasks[0]
    weather = task.weather.model_copy(update={field: value})
    assert gate(plan.spots[0], weather, plan.brief, task.start, task.end)


@pytest.mark.parametrize("field,value", [("unsafe", True), ("access", "CLOSED"), ("ticket_required", True)])
def test_access_gates(plan, field, value):
    task = plan.tasks[0]
    spot = plan.spots[0].model_copy(update={field: value})
    assert gate(spot, task.weather, plan.brief, task.start, task.end)


def test_closing_before_task_end(plan):
    task = plan.tasks[0]
    spot = plan.spots[0].model_copy(update={"open_until": task.end-timedelta(minutes=1)})
    assert gate(spot, task.weather, plan.brief, task.start, task.end)


def test_numeric_evidence_required(plan):
    broken = plan.model_dump()
    broken["tasks"][0]["camera"]["evidence_ids"] = []
    with pytest.raises(ValidationError):
        ShotPlan.model_validate(broken)


def test_missing_source_rejected(plan):
    broken = plan.model_dump()
    broken["sources"] = []
    with pytest.raises(ValidationError):
        ShotPlan.model_validate(broken)


def test_overlap_rejected(plan):
    broken = plan.model_dump()
    broken["tasks"][1]["start"] = broken["tasks"][0]["start"]
    with pytest.raises(ValidationError):
        ShotPlan.model_validate(broken)


@pytest.mark.parametrize("sensor,crop", [("full_frame", 1), ("aps_c", 1.5), ("m43", 2), ("phone", 1)])
def test_lens_and_crop(brief, sensor, crop):
    brief.sensor = sensor
    brief.lenses = [Lens(name="50mm F4", min_mm=50, max_mm=50, max_aperture=4)]
    result = camera_advice(brief, 1, Ledger())
    assert result.focal_mm == 50
    assert result.equivalent_mm == 50 * crop
    assert result.aperture >= 4
    assert result.shutter_seconds <= 1/250


def test_handheld_telephoto_night(brief):
    brief.genre = "cityscape"
    brief.lenses = [Lens(name="200mm F5.6", min_mm=200, max_mm=200, max_aperture=5.6)]
    result = camera_advice(brief, 0, Ledger())
    assert result.shutter_seconds <= 1/400
    assert result.aperture >= 5.6


def test_tripod_night(brief):
    brief.genre, brief.tripod = "cityscape", True
    result = camera_advice(brief, 0, Ledger())
    assert result.iso == 100
    assert result.shutter_seconds == 2


@pytest.mark.parametrize("source", ["road_traffic", "heatmap_renderer"])
def test_traffic_not_crowds(source):
    signal = CrowdSignal(level="HIGH", source_type=source, spatial_scope="湖岸", label="REPORTED", evidence_ids=["ev"])
    assert fresh_crowd(signal, datetime.now(UTC)).level == "UNKNOWN"


def test_stale_crowd():
    signal = CrowdSignal(level="HIGH", spatial_scope="湖岸", label="REPORTED", evidence_ids=["ev"],
        valid_until=datetime.now(UTC)-timedelta(minutes=5))
    assert fresh_crowd(signal, datetime.now(UTC)).label == "STALE"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "https://localhost/a", "http://127.0.0.1/a",
                                "https://user:password@example.com/a", "not a URL"])
def test_unsafe_url(url):
    assert canonical_url(url) is None


def test_no_official_domain_spoof():
    assert source_kind("https://nanjing.gov.cn.evil.com/a") != "official"
    assert source_kind("https://nanjing.gov.cn/a") == "official"
    assert source_kind("https://www.xiaohongshu.com/a") == "community"


def test_coordinate_roundtrip():
    assert gcj_to_wgs(*wgs_to_gcj(118.8, 32.06)) == pytest.approx([118.8, 32.06], abs=1e-5)


def test_non_china_coords_unchanged():
    assert wgs_to_gcj(-74, 40) == [-74, 40]


def test_polar_no_fake_sunset(brief):
    brief.travel_date = datetime(2026, 6, 21).date()
    solar = solar_windows(brief, Position(lat=89, lon=0, evidence_ids=["ev"]), Ledger())
    assert solar.sunset is None


@pytest.mark.parametrize("zone", ["Asia/Shanghai", "UTC", "America/New_York", "Pacific/Auckland"])
def test_valid_timezones(zone):
    assert TripBrief(timezone=zone).timezone == zone


def test_invalid_timezone():
    with pytest.raises(ValidationError):
        TripBrief(timezone="Invalid/Zone")


def test_inverted_time_window():
    with pytest.raises(ValidationError):
        TripBrief(start_local="20:00", end_local="18:00")


def test_inverted_lens():
    with pytest.raises(ValidationError):
        Lens(name="bad", min_mm=100, max_mm=20)


def test_naive_weather_timestamp_rejected(plan):
    data = plan.tasks[0].weather.model_dump()
    data["at"] = datetime(2026,10,3,10)
    with pytest.raises(ValidationError):
        type(plan.tasks[0].weather).model_validate(data)


def test_negative_route_rejected(plan):
    data = plan.routes[0].model_dump()
    data["distance_m"] = -100
    with pytest.raises(ValidationError):
        type(plan.routes[0]).model_validate(data)
