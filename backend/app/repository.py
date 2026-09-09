"""Transactional versions and compare-and-swap approval, shared by SQLite/PostgreSQL."""
import json

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError

from .models import PlanChangeProposal, ShotPlan


class Conflict(Exception):
    pass


class Repository:
    def __init__(self, url):
        self.engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
        meta = MetaData()
        self.plans = Table("plans", meta, Column("id", String, primary_key=True), Column("version", Integer),
                           Column("body", Text, nullable=False))
        self.versions = Table("plan_versions", meta, Column("plan_id", String, primary_key=True),
                              Column("version", Integer, primary_key=True), Column("reason", Text), Column("body", Text))
        self.proposals = Table("proposals", meta, Column("id", String, primary_key=True),
                               Column("plan_id", String), Column("status", String), Column("body", Text))
        self.requests = Table("requests", meta, Column("key", String, primary_key=True),
                              Column("fingerprint", String), Column("response", Text))
        meta.create_all(self.engine)
        self.spatial = self.engine.dialect.name == "postgresql"
        if self.spatial:
            from pathlib import Path
            migration = Path(__file__).resolve().parents[2] / "infra/migrations/001_spatial.sql"
            with self.engine.begin() as conn:
                for statement in migration.read_text(encoding="utf-8").split(";"):
                    if statement.strip():
                        conn.exec_driver_sql(statement)

    def sync_geometry(self, conn, plan):
        if not self.spatial:
            return
        conn.execute(text("DELETE FROM spot_geometry WHERE plan_id=:plan_id"), {"plan_id": plan.id})
        for spot in plan.spots:
            entries = [("camera", spot.camera), ("entrance", spot.entrance)]
            if spot.subjects:
                entries.append(("subject", spot.subjects[0].position))
            for role, point in entries:
                if point is None:
                    continue
                conn.execute(text("INSERT INTO spot_geometry(plan_id,spot_id,role,location,precision_label) "
                    "VALUES(:plan_id,:spot_id,:role,ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography,:precision)"),
                    {"plan_id":plan.id,"spot_id":spot.id,"role":role,"lat":point.lat,"lon":point.lon,
                     "precision":point.precision.value})

    def save(self, plan):
        body = plan.model_dump_json()
        with self.engine.begin() as conn:
            conn.execute(insert(self.plans).values(id=plan.id, version=plan.version, body=body))
            conn.execute(insert(self.versions).values(plan_id=plan.id, version=plan.version, reason="创建计划", body=body))
            self.sync_geometry(conn, plan)

    def get(self, plan_id):
        with self.engine.connect() as conn:
            body = conn.execute(select(self.plans.c.body).where(self.plans.c.id == plan_id)).scalar_one_or_none()
        if body is None:
            raise KeyError(plan_id)
        return ShotPlan.model_validate_json(body)

    def list(self):
        with self.engine.connect() as conn:
            rows = conn.execute(select(self.plans.c.body).limit(100)).scalars().all()
        plans = [ShotPlan.model_validate_json(row) for row in rows]
        return [{"id": p.id, "version": p.version, "destination": p.brief.destination,
                 "date": p.brief.travel_date.isoformat(), "genre": p.brief.genre} for p in reversed(plans)]

    def add_proposal(self, proposal):
        with self.engine.begin() as conn:
            conn.execute(insert(self.proposals).values(id=proposal.id, plan_id=proposal.plan_id,
                         status=proposal.status, body=proposal.model_dump_json()))

    def proposal(self, pid):
        with self.engine.connect() as conn:
            body = conn.execute(select(self.proposals.c.body).where(self.proposals.c.id == pid)).scalar_one_or_none()
        if body is None:
            raise KeyError(pid)
        return PlanChangeProposal.model_validate_json(body)

    def decide(self, pid, approve, version):
        with self.engine.begin() as conn:
            row = conn.execute(select(self.proposals).where(self.proposals.c.id == pid)).mappings().first()
            if not row:
                raise KeyError(pid)
            proposal = PlanChangeProposal.model_validate_json(row["body"])
            if row["status"] != "PENDING":
                raise Conflict("该提案已处理")
            if proposal.base_version != version:
                raise Conflict("提案版本不匹配")
            if approve:
                plan = proposal.proposed.model_copy(update={"version": version + 1})
                affected = conn.execute(update(self.plans).where(self.plans.c.id == proposal.plan_id,
                    self.plans.c.version == version).values(version=version + 1, body=plan.model_dump_json())).rowcount
                if affected != 1:
                    raise Conflict("计划已被修改，请刷新并重新生成提案")
                conn.execute(insert(self.versions).values(plan_id=plan.id, version=plan.version,
                             reason=proposal.reason, body=plan.model_dump_json()))
                self.sync_geometry(conn, plan)
            proposal.status = "APPROVED" if approve else "REJECTED"
            changed = conn.execute(update(self.proposals).where(self.proposals.c.id == pid,
                self.proposals.c.status == "PENDING").values(status=proposal.status, body=proposal.model_dump_json())).rowcount
            if changed != 1:
                raise Conflict("提案已由其他请求处理")
        return self.get(proposal.plan_id)

    def undo(self, plan_id, version):
        if version <= 1:
            raise Conflict("没有可撤销版本")
        with self.engine.begin() as conn:
            body = conn.execute(select(self.versions.c.body).where(self.versions.c.plan_id == plan_id,
                self.versions.c.version == version - 1)).scalar_one_or_none()
            if not body:
                raise Conflict("历史版本不存在")
            restored = ShotPlan.model_validate_json(body).model_copy(update={"version": version + 1})
            changed = conn.execute(update(self.plans).where(self.plans.c.id == plan_id,
                self.plans.c.version == version).values(version=version + 1, body=restored.model_dump_json())).rowcount
            if changed != 1:
                raise Conflict("版本冲突，请刷新")
            conn.execute(insert(self.versions).values(plan_id=plan_id, version=version + 1,
                         reason=f"撤销版本 {version}", body=restored.model_dump_json()))
            self.sync_geometry(conn, restored)
        return restored

    def history(self, plan_id):
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(select(self.versions.c.version, self.versions.c.reason)
                    .where(self.versions.c.plan_id == plan_id).order_by(self.versions.c.version)).mappings()]

    def reserve(self, key, fingerprint, response):
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(self.requests).values(key=key, fingerprint=fingerprint, response=json.dumps(response)))
            return response, True
        except IntegrityError:
            with self.engine.connect() as conn:
                row = conn.execute(select(self.requests).where(self.requests.c.key == key)).mappings().one()
                if row["fingerprint"] != fingerprint:
                    raise Conflict("幂等键已用于不同请求") from None
                return json.loads(row["response"]), False
