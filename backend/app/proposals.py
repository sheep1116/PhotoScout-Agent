from uuid import uuid4

from .models import FieldDiff, PlanChangeProposal, ShotPlan, TruthLabel


def field_diff(before, after, prefix=""):
    changes = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            changes += field_diff(before.get(key), after.get(key), f"{prefix}/{key}")
    elif isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        for i, (a, b) in enumerate(zip(before, after)):
            changes += field_diff(a, b, f"{prefix}/{i}")
    elif before != after:
        changes.append(FieldDiff(path=prefix, before=before, after=after))
    return changes


def propose(plan, task_id, reason):
    changed = plan.model_copy(deep=True)
    task = next((t for t in changed.tasks if t.id == task_id), None)
    if task is None:
        raise KeyError(task_id)
    if task.status == "CANCELLED":
        raise ValueError("该任务已取消")
    task.status = "CANCELLED"
    task.risks.append(reason)
    task.alternative = "取消本段户外拍摄，保留其他安排。若转入室内，先自行确认入口、开放与安全。"
    # Keep source weather intact: a scenario simulation is not a real observation.
    from .models import Evidence, WebSource
    eid = "ev-change-" + uuid4().hex[:12]
    sid = "src-" + eid
    changed.sources.append(WebSource(id=sid, title="用户请求/演示情景", publisher="PhotoScout", kind="user"))
    changed.evidence.append(Evidence(id=eid, source_id=sid, label=TruthLabel.USER_CONFIRMED,
                                    statement=reason + "；这是变更原因，不代表官方气象或开放事实。"))
    task.evidence_ids.append(eid)
    changed = ShotPlan.model_validate(changed.model_dump())
    return PlanChangeProposal(id=uuid4().hex, plan_id=plan.id, base_version=plan.version, reason=reason,
        diff=field_diff(plan.model_dump(mode="json"), changed.model_dump(mode="json")), proposed=changed)
