import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.main import create_app
from backend.app.models import ReverseContext, ShotPlan
from backend.app.reference_photos import ReferenceStore, decode_photo
from backend.app.repository import Repository
from backend.app.reverse_planning import analyze_reference, field_of_view, nd_exposure, recreate
from backend.app.vision import VisualAnalysis


def picture():
    stream=io.BytesIO()
    exif=Image.Exif()
    exif[271]='Test camera'
    exif[41989]=85
    exif[37500]=b'private maker note'
    Image.new('RGB',(120,80),'#7799aa').save(stream,format='JPEG',exif=exif)
    return stream.getvalue()


def test_image_decoder_strips_metadata_and_rejects_bad_formats():
    clean,metadata=decode_photo(picture())
    assert metadata['exif']['make']=='Test camera'
    assert metadata['exif']['equivalent_mm']==85
    assert 'private maker note' not in str(metadata)
    with Image.open(io.BytesIO(clean)) as image:
        assert not image.getexif()
    with pytest.raises(ValueError):
        decode_photo(b'<svg><script>bad</script></svg>')
    with pytest.raises(ValueError):
        decode_photo(b'a'*(10*1024*1024+1))


def test_reference_api_private_preview_delete_and_bad_upload(settings):
    with TestClient(create_app(settings)) as client:
        assert client.post('/v1/reference-photos',content=b'bad',headers={'Content-Type':'image/jpeg'}).status_code==422
        assert client.post('/v1/reference-photos',content=b'<svg/>',headers={'Content-Type':'image/svg+xml'}).status_code==415
        response=client.post('/v1/reference-photos',content=picture(),headers={'Content-Type':'image/jpeg'})
        assert response.status_code==201
        identifier=response.json()['id']
        preview=client.get(f'/v1/reference-photos/{identifier}/preview')
        assert preview.headers['cache-control']=='no-store'
        assert not Image.open(io.BytesIO(preview.content)).getexif()
        assert client.delete(f'/v1/reference-photos/{identifier}').status_code==200
        assert client.get(f'/v1/reference-photos/{identifier}').status_code==404


async def test_reverse_reuses_candidates_and_evidence_across_dates(settings,brief,monkeypatch):
    repo=Repository(settings.database_url)
    store=ReferenceStore(repo.engine)
    photo=store.upload(picture())
    brief.travel_date=datetime.now(ZoneInfo(brief.timezone)).date()+timedelta(days=1)
    brief.end_date=brief.travel_date
    identifier='a'*32
    async def emit(*args):
        pass
    body=await analyze_reference(identifier,photo['id'],brief,'similar',store,settings,emit)
    assert len(body['spots'])==3
    assert body['visual']['summary'].startswith('离线示例')
    # Persisted data survives a new store instance; no second candidate search is allowed.
    store=ReferenceStore(repo.engine)
    async def no_discovery(*args):
        raise AssertionError('repeated discovery')
    monkeypatch.setattr('backend.app.providers.Providers.discover',no_discovery)
    brief.reverse_context=ReverseContext(analysis_id=identifier,spot_id=body['spots'][0]['id'],days=3)
    plan=await recreate('reverse-test',brief,store,settings,emit)
    ShotPlan.model_validate(plan.model_dump())
    assert plan.recreation['evaluated_days']==3
    assert len(plan.recreation['windows'])==3
    assert not plan.routes and len(plan.tasks)==1
    assert plan.tasks[0].camera.focal_mm==35  # user's fixed lens constrains EXIF 85 mm target
    assert plan.recreation['location_confidence']=='low'
    all_ids={e.id for e in plan.evidence}
    assert all(set(w['evidence_ids'])<=all_ids for w in plan.recreation['windows'])
    assert any(e.label=='USER_CONFIRMED' for e in plan.evidence)
    store.delete(photo['id'])
    with pytest.raises(KeyError):
        await recreate('deleted',brief,store,settings,emit)


async def test_no_region_returns_analysis_without_guessing(settings,brief):
    repo=Repository(settings.database_url)
    store=ReferenceStore(repo.engine)
    photo=store.upload(picture())
    brief.destination=''
    async def emit(*args):
        pass
    body=await analyze_reference('b'*32,photo['id'],brief,'original',store,settings,emit)
    assert body['visual'] and not body['spots']
    assert body['warnings']


def test_optics_and_vision_schema_boundaries():
    assert nd_exposure(1/60,6)==pytest.approx(64/60)
    assert field_of_view(50,36)==pytest.approx(39.59775,rel=.001)
    with pytest.raises(ValueError):
        VisualAnalysis(summary='test',latitude=32)
    with pytest.raises(ValueError):
        ReverseContext(analysis_id='a'*32,spot_id='x',days=365)


def test_reference_jobs_complete_on_shared_status_endpoint(settings,brief):
    with TestClient(create_app(settings)) as client:
        identifier=client.post('/v1/reference-photos',content=picture(),headers={'Content-Type':'image/jpeg'}).json()['id']
        started=client.post(f'/v1/reference-photos/{identifier}/analysis',json={'brief':brief.model_dump(mode='json'),'mode':'original'})
        assert started.status_code==202
        job_id=started.json()['research_id']
        for _ in range(30):
            job=client.get('/v1/photo-research/'+job_id).json()
            if job['status']!='running':
                break
            import time
            time.sleep(.02)
        assert job['status']=='complete'
        body=client.get('/v1/reference-analyses/'+job_id).json()
        assert body['spots']
        client.delete('/v1/reference-photos/'+identifier)
        assert client.get('/v1/reference-analyses/'+job_id).status_code==404


def test_latest_reference_result_is_listed_after_more_than_100_plans(settings,plan):
    from sqlalchemy import insert
    repo=Repository(settings.database_url)
    rows=[]
    for index in range(102):
        item=plan.model_copy(deep=True)
        item.id=f'plan-{index}'
        item.created_at=plan.created_at+timedelta(seconds=index)
        rows.append({'id':item.id,'version':1,'body':item.model_dump_json()})
    with repo.engine.begin() as conn:
        conn.execute(insert(repo.plans),rows)
    summaries=repo.list()
    assert len(summaries)==100 and summaries[0]['id']=='plan-101'
    assert all(s['id']!='plan-0' for s in summaries)


def test_reference_weather_changes_scoring_without_filtering(brief):
    from backend.app.engine import Ledger
    from backend.app.fixtures import seed_conditions, seed_spots
    from backend.app.recommendations import build_recommendations, reference_weather_penalty
    ledger=Ledger()
    spots,claims=seed_spots(brief,ledger)
    weather=seed_conditions(brief,ledger)
    clear=weather[0].model_copy(update={'cloud_pct':0})
    cloudy=weather[0].model_copy(update={'cloud_pct':90})
    assert reference_weather_penalty(clear,{'weather':'overcast'}) < reference_weather_penalty(cloudy,{'weather':'overcast'})
    plan=build_recommendations('reference-weather',brief,spots,claims,{s.id:weather for s in spots},ledger,[],reference={'weather':'overcast'})
    assert len(plan.tasks)==4
    assert all('参考天气匹配' in t.score.adjustments for t in plan.tasks)


async def test_visual_cache_and_explicit_preferences_are_preserved(settings,brief,monkeypatch):
    from backend.app.reverse_planning import photo_intent
    visual=VisualAnalysis(summary='test',light='night')
    brief.intent.light='daylight'
    brief.edited_fields=['light']
    brief.intent.preferences.avoid_tickets=True
    intent=photo_intent(visual,brief)
    assert intent.light=='daylight' and intent.preferences.avoid_tickets
    store=ReferenceStore(Repository(settings.database_url).engine)
    photo=store.upload(picture())
    brief.destination=''
    async def emit(*args):
        pass
    first=await analyze_reference('c'*32,photo['id'],brief,'original',store,settings,emit)
    second=await analyze_reference('d'*32,photo['id'],brief,'similar',store,settings,emit)
    assert first['visual']==second['visual']
    assert second['usage']['cache_hit']


async def test_vision_receives_only_clean_image_and_rejects_invented_fields(settings,respx_mock):
    import base64
    import json

    from pydantic import SecretStr

    from backend.app.providers import Providers
    from backend.app.vision import understand
    settings.dashscope_api_key=SecretStr('vision-test-secret')
    clean,_=decode_photo(picture())
    route=respx_mock.post(settings.dashscope_native_base_url+'/services/aigc/multimodal-generation/generation').respond(200,json={'output':{'choices':[{'message':{'content':[{'text':json.dumps({'summary':'一张测试照片','hypotheses':[]})}]}}]},'usage':{'input_tokens':12}})
    network=Providers(settings)
    try:
        visual,usage=await understand(clean,network)
    finally:
        await network.client.aclose()
    payload=json.loads(route.calls[0].request.content)
    encoded=payload['input']['messages'][1]['content'][0]['image'].split(',',1)[1]
    assert not Image.open(io.BytesIO(base64.b64decode(encoded))).getexif()
    assert 'vision-test-secret' not in str(payload)
    assert payload['parameters']['enable_search'] is False
    assert not visual.hypotheses and usage['input_tokens']==12
