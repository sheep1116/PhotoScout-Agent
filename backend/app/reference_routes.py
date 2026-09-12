"""Reference uploads and analysis use the existing in-process job/SSE lifecycle."""
import asyncio
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import Response
from pydantic import Field

from .destinations import resolve_notebook
from .engine import notebook
from .models import Model, TripBrief
from .providers import Providers
from .reference_photos import MAX_BYTES, ReferenceStore
from .reverse_planning import analyze_reference


class AnalysisRequest(Model):
    brief: TripBrief
    mode: str = Field(default='original',pattern='^(original|similar)$')


def register_reference_routes(app,settings,repo,jobs,workers):
    store=ReferenceStore(repo.engine)
    app.state.references=store
    slots=asyncio.Semaphore(2)

    @app.post('/v1/reference-photos',status_code=201)
    async def upload(request:Request):
        if request.headers.get('content-type','').split(';')[0] not in ('image/jpeg','image/png','image/webp','application/octet-stream'):
            raise HTTPException(415,'仅支持 JPEG、PNG、WebP 图片')
        async with slots:
            raw=bytearray()
            async for chunk in request.stream():
                if len(raw)+len(chunk)>MAX_BYTES:
                    raise HTTPException(413,'图片须小于 10 MB')
                raw.extend(chunk)
            try:
                return await asyncio.to_thread(store.upload,bytes(raw))
            except (ValueError,TypeError,OverflowError):
                raise HTTPException(422,'无法读取图片；请使用 10 MB、2400 万像素以内的静态 JPEG/PNG/WebP') from None

    @app.get('/v1/reference-photos/{photo_id}')
    def metadata(photo_id:str):
        return store.photo(photo_id)[1]

    @app.get('/v1/reference-photos/{photo_id}/preview')
    def preview(photo_id:str):
        return Response(store.photo(photo_id)[0],media_type='image/jpeg',headers={'Cache-Control':'no-store','Content-Security-Policy':"default-src 'none'; sandbox"})

    @app.delete('/v1/reference-photos/{photo_id}')
    def remove(photo_id:str):
        store.photo(photo_id)
        # Prevent completion from recreating analysis after deletion.
        for identifier,job in jobs.items():
            if job.get('photo_id')==photo_id:
                job.update(status='failed',error='参考图已删除')
                for task in workers:
                    if task.get_name()==identifier:
                        task.cancel()
        store.delete(photo_id)
        return {'deleted':True}

    @app.get('/v1/reference-analyses/{identifier}')
    def analysis(identifier:str):
        return store.analysis(identifier)

    @app.get('/v1/reference-analyses/{identifier}/photos/{photo_id}')
    async def candidate_photo(identifier:str,photo_id:str):
        from .media import fetch_image
        from .models import PhotoSpot
        saved=store.analysis(identifier)
        photo=next((p for spot in saved['spots'] for p in PhotoSpot.model_validate(spot).photo_references if p.id==photo_id),None)
        if photo is None:
            raise HTTPException(404,'候选参考图不存在')
        try:
            async with slots:
                async with asyncio.timeout(15):
                    raw,mime=await fetch_image(str(photo.image_url))
            return Response(raw,media_type=mime,headers={'Cache-Control':'private, max-age=300','Content-Security-Policy':"default-src 'none'; sandbox"})
        except Exception:
            raise HTTPException(502,'候选参考图暂不可用') from None

    @app.post('/v1/reference-photos/{photo_id}/analysis',status_code=202)
    async def start_analysis(photo_id:str,body:AnalysisRequest):
        store.photo(photo_id)
        if len([j for j in jobs.values() if j['status']=='running'])>=3:
            raise HTTPException(429,'已有多个生成任务，请稍后重试')
        network=Providers(settings)
        try:
            book=await resolve_notebook(notebook(body.brief),network)
        finally:
            await network.client.aclose()
        if any(field!='destination' for field in book.missing_fields) or book.location_status in ('needs_choice','unavailable'):
            return {'status':'needs_clarification','notebook':book.model_dump(mode='json')}
        if len(jobs)>=100:
            for identifier in list(jobs):
                if jobs[identifier]['status']!='running':
                    del jobs[identifier]
                    break
        identifier=uuid4().hex
        jobs[identifier]={'status':'running','events':[],'photo_id':photo_id,'kind':'reference_analysis'}
        async def emit(stage,message):
            if jobs[identifier]['status']!='running':
                raise asyncio.CancelledError()
            jobs[identifier]['events'].append({'stage':stage,'message':message})
        async def run():
            try:
                async with asyncio.timeout(180):
                    await analyze_reference(identifier,photo_id,book.brief,body.mode,store,settings,emit)
                jobs[identifier].update(status='complete',analysis_id=identifier)
            except asyncio.CancelledError:
                jobs[identifier].update(status='failed',error='分析已取消或服务重启')
            except Exception:
                jobs[identifier].update(status='failed',error='分析或地点服务暂不可用；已完成的画面分析仍可查看，请补充地点后重试')
        task=asyncio.create_task(run(),name=identifier)
        workers.add(task)
        task.add_done_callback(workers.discard)
        return {'research_id':identifier,'analysis_id':identifier,'status':'running'}
    return store
