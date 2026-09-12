import asyncio
import hashlib
import json
import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .changes import position_proposal, refresh_proposal
from .config import Settings
from .destinations import resolve_notebook
from .engine import notebook
from .graph import run_graph
from .intent_parser import parse_description
from .location import Coordinates, locate
from .models import TripBrief
from .proposals import propose
from .providers import ProviderError, Providers
from .repository import Conflict, Repository

# Avoid upstream client logs containing query-string API credentials.
logging.getLogger("httpx").setLevel(logging.CRITICAL)
logging.getLogger("httpcore").setLevel(logging.CRITICAL)


class ChangeRequest(BaseModel):
    task_id: str
    reason: str = Field(min_length=2, max_length=300)
    version: int = Field(ge=1)


class Decision(BaseModel):
    approve: bool
    version: int = Field(ge=1)


class VersionRequest(BaseModel):
    version: int = Field(ge=1)


class PositionRequest(VersionRequest):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    role: str = Field(pattern="^(camera|entrance)$")


def create_app(settings=None, repository=None):
    settings = settings or Settings()
    repo = repository or Repository(settings.database_url)
    jobs, workers = {}, set()
    media_slots = asyncio.Semaphore(4)

    @asynccontextmanager
    async def lifespan(app):
        yield
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    app = FastAPI(title="PhotoScout Agent", version="0.2.0", lifespan=lifespan)
    app.state.repo = repo
    from .reference_routes import register_reference_routes
    from .reverse_planning import recreate
    references = register_reference_routes(app, settings, repo, jobs, workers)

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(KeyError)
    async def not_found(request, exc):
        return JSONResponse(status_code=404, content={"detail": "记录不存在"})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, exc):
        return JSONResponse(status_code=422, content={"detail": "输入字段无效，请检查日期、时间、镜头和范围。",
            "fields": [".".join(map(str, e["loc"])) for e in exc.errors()]})

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
            from urllib.parse import urlsplit
            if urlsplit(origin).netloc != request.headers.get("host") and origin not in settings.frontend_origins:
                return JSONResponse(status_code=403, content={"detail": "不允许跨站写入"})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/v1/plans/{plan_id}/photos/{photo_id}")
    async def photo(plan_id: str, photo_id: str):
        from fastapi.responses import Response

        from .media import fetch_image
        current = repo.get(plan_id)
        item = next((p for spot in current.spots for p in spot.photo_references if p.id == photo_id), None)
        if item is None:
            raise HTTPException(404, "参考图不存在")
        try:
            async with asyncio.timeout(15):
                async with media_slots:
                    raw, mime = await fetch_image(str(item.image_url))
            return Response(raw, media_type=mime, headers={"Cache-Control": "private, max-age=300",
                "Content-Security-Policy": "default-src 'none'; sandbox", "X-Content-Type-Options": "nosniff"})
        except Exception:
            raise HTTPException(502, "参考图暂时不可用，请查看原始来源") from None

    @app.get("/v1/location/ip")
    async def location_ip():
        return await locate(settings)

    @app.post("/v1/location/reverse")
    async def location_reverse(body: Coordinates):
        return await locate(settings, body)

    @app.get("/v1/health")
    def health():
        return {"status": "ok", **settings.public_status()}

    @app.post("/v1/notebook")
    async def parse_brief(brief: TripBrief):
        network = Providers(settings)
        try:
            return await resolve_notebook(await parse_description(brief, network), network)
        finally:
            await network.client.aclose()

    @app.post("/v1/destinations/resolve")
    async def resolve_destination(brief: TripBrief):
        network = Providers(settings)
        try:
            return await resolve_notebook(notebook(brief), network)
        finally:
            await network.client.aclose()

    async def worker(job_id, brief):
        job = jobs[job_id]

        async def emit(stage, message):
            job["events"].append({"stage": stage, "message": message})
        try:
            async with asyncio.timeout(180):
                plan = await recreate(job_id, brief, references, settings, emit) if brief.reverse_context else await run_graph(job_id, brief, settings, emit)
                repo.save(plan)
                job["status"] = "complete"
                await emit("complete", "拍摄草案已保存")
        except asyncio.CancelledError:
            job.update(status="failed", error="服务重启，生成中断，请重新生成")
            raise
        except (ProviderError, ValueError) as exc:
            job.update(status="failed", error=str(exc) if isinstance(exc, ProviderError) else "生成失败：请检查目的地与必填信息")
            await emit("failed", job["error"])
        except Exception:
            job.update(status="failed", error="生成暂时失败；未保存不完整计划，请重试或使用离线 Demo")
            await emit("failed", job["error"])

    @app.post("/v1/photo-research", status_code=202)
    async def create_research(brief: TripBrief, idempotency_key: str | None = Header(default=None)):
        if brief.reverse_context:
            saved = references.analysis(brief.reverse_context.analysis_id)
            chosen = next((s for s in saved['spots'] if s['id'] == brief.reverse_context.spot_id),None)
            if chosen is None or saved.get('vision_version') != 2:
                raise HTTPException(422, "请选择新版分析中已匹配地图的候选机位")
            if saved['data_mode'] != brief.mode:
                raise HTTPException(422, "图片分析与规划的数据模式不一致")
            candidate = next(c for c in saved['candidates'] if c['spot_id'] == chosen['id'])
            brief.destination = candidate['city'] or chosen['place']['name']
            brief.location = None
            book = notebook(brief)  # Coordinates come from the selected server-side spot.
        else:
            network = Providers(settings)
            try:
                book = await resolve_notebook(notebook(brief), network)
            finally:
                await network.client.aclose()
        if book.missing_fields or book.location_status in ("needs_choice", "unavailable"):
            return {"status": "needs_clarification", "notebook": book.model_dump(mode="json")}
        if book.brief.mode == "mock" and "南京" not in book.brief.destination:
            raise HTTPException(422, "离线演示仅包含南京；其他目的地请切换 Live 模式")
        if len([j for j in jobs.values() if j["status"] == "running"]) >= 3:
            raise HTTPException(429, "已有多个生成任务，请稍后重试")
        job_id = uuid4().hex
        response = {"research_id": job_id, "status": "running"}
        if idempotency_key:
            if len(idempotency_key) > 128:
                raise HTTPException(422, "幂等键过长")
            fingerprint = hashlib.sha256(book.brief.model_dump_json().encode()).hexdigest()
            response, fresh = repo.reserve(idempotency_key, fingerprint, response)
            if not fresh:
                return response
        if len(jobs) >= 100:
            for key in list(jobs):
                if jobs[key]["status"] != "running":
                    del jobs[key]
                    break
        jobs[job_id] = {"status": "running", "events": []}
        if brief.reverse_context:
            jobs[job_id]['photo_id'] = saved['photo_id']
        task = asyncio.create_task(worker(job_id, book.brief), name=job_id)
        workers.add(task)
        task.add_done_callback(workers.discard)
        return response

    @app.get("/v1/photo-research/{job_id}")
    def job_status(job_id):
        if job_id in jobs:
            return {"research_id": job_id, **jobs[job_id]}
        try:
            repo.get(job_id)
            return {"research_id": job_id, "status": "complete", "events": []}
        except KeyError:
            return {"research_id": job_id, "status": "failed", "error": "任务不存在或服务重启后中断，请重新生成"}

    @app.get("/v1/photo-research/{job_id}/events")
    async def events(job_id, request: Request):
        async def stream():
            cursor = 0
            while not await request.is_disconnected():
                job = job_status(job_id)
                for event in job.get("events", [])[cursor:]:
                    cursor += 1
                    yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if job["status"] != "running":
                    yield f"event: done\ndata: {json.dumps(job, ensure_ascii=False)}\n\n"
                    return
                yield ": heartbeat\n\n"
                await asyncio.sleep(.4)
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/v1/plans")
    def plans():
        return repo.list()

    @app.get("/v1/plans/{plan_id}")
    def plan(plan_id):
        return repo.get(plan_id)

    @app.get("/v1/plans/{plan_id}/history")
    def history(plan_id):
        return repo.history(plan_id)

    @app.get("/v1/photo-research/{job_id}/spots")
    def spots(job_id):
        return repo.get(job_id).spots

    @app.post("/v1/plans/{plan_id}/proposals")
    def proposal(plan_id, change: ChangeRequest):
        current = repo.get(plan_id)
        if current.version != change.version:
            raise Conflict("版本冲突，请刷新计划")
        try:
            result = propose(current, change.task_id, change.reason)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        repo.add_proposal(result)
        return result

    @app.post("/v1/proposals/{proposal_id}/decision")
    def decide(proposal_id, decision: Decision):
        return repo.decide(proposal_id, decision.approve, decision.version)

    @app.post("/v1/plans/{plan_id}/undo")
    def undo(plan_id, body: VersionRequest):
        return repo.undo(plan_id, body.version)

    @app.get("/v1/plans/{plan_id}/evidence/{evidence_id}")
    def evidence(plan_id, evidence_id):
        item = next((e for e in repo.get(plan_id).evidence if e.id == evidence_id), None)
        if item is None:
            raise KeyError(evidence_id)
        return item

    @app.post("/v1/plans/{plan_id}/spots/{spot_id}/confirm")
    def confirm_position(plan_id, spot_id, body: PositionRequest):
        current = repo.get(plan_id)
        if current.version != body.version:
            raise Conflict("版本冲突，请刷新计划")
        try:
            proposal = position_proposal(current, spot_id, body.lat, body.lon, body.role)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        repo.add_proposal(proposal)
        return proposal

    @app.post("/v1/plans/{plan_id}/refresh")
    async def refresh(plan_id, body: VersionRequest):
        current = repo.get(plan_id)
        if current.version != body.version:
            raise Conflict("版本冲突，请刷新计划")
        providers = Providers(settings)
        try:
            proposal = await refresh_proposal(current, providers)
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from None
        finally:
            await providers.client.aclose()
        if proposal:
            repo.add_proposal(proposal)
        return {"proposal": proposal, "message": "已生成天气变更提案" if proposal else "没有需要修改的材料变化，或数据仍有效；离线模式请使用模拟按钮。"}

    return app


app = create_app()
