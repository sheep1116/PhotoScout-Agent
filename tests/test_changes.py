from datetime import UTC, datetime, timedelta

import pytest

from backend.app.changes import position_proposal, refresh_proposal
from backend.app.models import SourceClaim, WebSource
from backend.app.verification import resolve_access


def test_position_proposal_not_permission(plan):
    spot = plan.spots[0]
    proposal = position_proposal(plan, spot.id, spot.camera.lat + .001, spot.camera.lon, "camera")
    assert proposal.proposed.spots[0].access == "UNKNOWN"
    assert plan.spots[0].camera.lat != proposal.proposed.spots[0].camera.lat
    assert proposal.proposed.spots[0].camera.precision == "MAP_POINT"
    assert proposal.proposed.tasks[1:] == plan.tasks[1:]


def test_far_position_rejected(plan):
    with pytest.raises(ValueError):
        position_proposal(plan, plan.spots[0].id, 40, 116, "camera")


def test_official_conflict():
    current = datetime.now(UTC)
    source = WebSource(id="s", title="官方", publisher="政府", kind="official", url="https://www.nanjing.gov.cn")
    claims = [SourceClaim(id=str(i),source_id="s",subject_id="a",kind="access",statement=state,
              label="VERIFIED", valid_until=current+timedelta(hours=1),evidence_ids=["ev"]) for i,state in enumerate(["OPEN","CLOSED"])]
    assert resolve_access(claims,[source],current) == "CONFLICT"
    source.kind = "community"
    assert resolve_access(claims,[source],current) == "UNKNOWN"
    source.kind = "official"
    assert resolve_access(claims,[source],current+timedelta(hours=2)) == "UNKNOWN"


async def test_material_weather_changes_only_affected(plan):
    plan.brief.mode = "live"
    class Provider:
        async def weather(self, brief, position, ledger):
            values = []
            for i, task in enumerate(plan.tasks):
                ids = ledger.add(str(i),"刷新模拟天气","FIXTURE","测试数值")
                values.append(task.weather.model_copy(update={"at":task.start, "wind_kmh":60 if i==0 else 8,
                                                            "evidence_ids":ids}))
            return values
    proposal = await refresh_proposal(plan, Provider())
    assert proposal.proposed.tasks[0].status == "CANCELLED"
    assert proposal.proposed.tasks[1:] == plan.tasks[1:]


async def test_refresh_failure_preserves_original(plan):
    plan.brief.mode = "live"
    class Provider:
        async def weather(self, brief, position, ledger):
            return [plan.tasks[0].weather.model_copy(update={"label":"UNKNOWN"})]
    with pytest.raises(ValueError):
        await refresh_proposal(plan, Provider())
    assert plan.version == 1
    assert plan.tasks[0].status != "CANCELLED"
