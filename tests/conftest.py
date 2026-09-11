import pytest

from backend.app.config import Settings
from backend.app.engine import Ledger, build_plan
from backend.app.fixtures import seed_conditions, seed_routes, seed_spots
from backend.app.models import Lens, TripBrief


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, dashscope_api_key="", amap_web_service_key="", flickr_api_key="", enable_external_photos=False, enable_community=False,
                    database_url=f"sqlite:///{tmp_path / 'test.db'}", provider_timeout=.1, amap_min_interval=0)


@pytest.fixture
def brief():
    return TripBrief(destination="南京紫金山", travel_date="2026-10-03", start_local="14:00", end_local="19:00",
        genre="portrait", lenses=[Lens(name="35mm F1.8", min_mm=35, max_mm=35, max_aperture=1.8)])


def make_plan(brief):
    ledger = Ledger()
    spots, claims = seed_spots(brief, ledger)
    conditions = seed_conditions(brief, ledger)
    routes = seed_routes(spots, ledger)
    return build_plan("test-plan", brief, spots, claims, conditions, routes, ledger, [])


@pytest.fixture
def plan(brief):
    return make_plan(brief)
