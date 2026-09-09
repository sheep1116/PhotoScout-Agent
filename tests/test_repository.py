import concurrent.futures

import pytest

from backend.app.proposals import propose
from backend.app.repository import Conflict, Repository


def test_approval_and_undo(settings, plan):
    repo = Repository(settings.database_url)
    repo.save(plan)
    proposal = propose(plan, plan.tasks[0].id, "模拟降雨")
    repo.add_proposal(proposal)
    assert repo.get(plan.id).model_dump() == plan.model_dump()
    changed = repo.decide(proposal.id, True, 1)
    assert changed.version == 2
    assert changed.tasks[0].status == "CANCELLED"
    assert changed.tasks[1:] == plan.tasks[1:]
    restored = repo.undo(plan.id, 2)
    assert restored.version == 3
    assert restored.tasks == plan.tasks
    assert len(repo.history(plan.id)) == 3


def test_rejection_no_change(settings, plan):
    repo = Repository(settings.database_url)
    repo.save(plan)
    proposal = propose(plan, plan.tasks[0].id, "入口未知")
    repo.add_proposal(proposal)
    assert repo.decide(proposal.id, False, 1) == plan


def test_stale_proposal_conflict(settings, plan):
    repo = Repository(settings.database_url)
    repo.save(plan)
    p1 = propose(plan, plan.tasks[0].id, "模拟降雨")
    p2 = propose(plan, plan.tasks[1].id, "模拟关闭")
    for p in [p1, p2]:
        repo.add_proposal(p)
    repo.decide(p1.id, True, 1)
    with pytest.raises(Conflict):
        repo.decide(p2.id, True, 1)
    assert repo.get(plan.id).tasks[1].status != "CANCELLED"


def test_concurrent_approval_exactly_once(settings, plan):
    repo = Repository(settings.database_url)
    repo.save(plan)
    p = propose(plan, plan.tasks[0].id, "模拟降雨")
    repo.add_proposal(p)
    def approve():
        try:
            repo.decide(p.id, True, 1)
            return True
        except Conflict:
            return False
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(lambda _: approve(), range(2))) == [False, True]


def test_idempotency(settings):
    repo = Repository(settings.database_url)
    assert repo.reserve("key", "a", {"id": 1})[1]
    assert not repo.reserve("key", "a", {"id": 2})[1]
    with pytest.raises(Conflict):
        repo.reserve("key", "b", {})


def test_reopen_database(settings, plan):
    Repository(settings.database_url).save(plan)
    assert Repository(settings.database_url).get(plan.id) == plan
