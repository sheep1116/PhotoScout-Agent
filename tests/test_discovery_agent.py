from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.app.destinations import resolve_notebook
from backend.app.engine import Ledger, camera_advice, notebook, score, solar_windows
from backend.app.fixtures import seed_conditions, seed_spots
from backend.app.intent_parser import parse_description
from backend.app.main import create_app
from backend.app.models import PhotographyIntent, Subject
from backend.app.providers import Providers
from backend.app.recommendations import build_recommendations


def candidates(brief, weather_changes=None, edit=None):
    ledger = Ledger()
    spots, claims = seed_spots(brief, ledger)
    if edit:
        edit(spots)
    weather = [w.model_copy(update=weather_changes or {}) for w in seed_conditions(brief, ledger)]
    return build_recommendations('soft', brief, spots, claims, {s.id: weather for s in spots}, ledger, [])


def test_two_mapped_subjects_produce_bearings_and_framing_assessment(brief):
    def add_second_subject(spots):
        first = spots[0]
        first.subjects = [Subject(name=first.subjects[0].name, position=spots[1].camera),
                          Subject(name="第二主体", position=first.place.position)]
    plan = candidates(brief, edit=add_second_subject)
    task = next(task for task in plan.tasks if task.spot_id == plan.spots[0].id)
    assert len(task.subject_bearings_deg) == 2
    assert task.subject_separation_deg is not None and task.field_of_view_deg is not None
    assert "方位跨度" in task.framing_assessment


@pytest.mark.parametrize('changes', [{'precipitation_mm': 3, 'cloud_pct': 95}, {'wind_kmh': 65}, {'weather_code': 95}])
def test_bad_weather_keeps_places_and_lowers_scores(brief, changes):
    brief.intent.light = 'golden_hour'
    good, bad = candidates(brief), candidates(brief, changes)
    assert len(good.tasks) == len(bad.tasks) == 4
    assert not bad.excluded and bad.tasks[0].alerts
    assert bad.tasks[0].score.suitability < good.tasks[0].score.suitability
    if 'precipitation_mm' in changes:
        assert any('可见机会较低' in a for a in bad.tasks[0].alerts)


def test_incompatible_light_keeps_place(brief):
    brief.intent.light = 'night'
    brief.start_local = datetime.strptime('10:00','%H:%M').time()
    brief.end_local = datetime.strptime('12:00','%H:%M').time()
    plan = candidates(brief)
    assert len(plan.tasks) == 4
    assert all(any('当前时间条件不理想' in a for a in t.alerts) for t in plan.tasks)


def test_soft_and_explicit_free_requirements(brief):
    brief.intent.preferences.avoid_tickets = True
    def edit(spots):
        spots[0].ticket_required = True
    soft = candidates(brief, edit=edit)
    assert len(soft.tasks) == 4 and soft.tasks[-1].spot_id == soft.spots[0].id
    brief.intent.preferences.strict = ['free']
    strict = candidates(brief, edit=edit)
    assert len(strict.tasks) == 3 and len(strict.excluded) == 1


def test_distance_is_soft_and_unknown_crowd_is_not_a_filter(brief):
    brief.origin_lat, brief.origin_lon = 32.05, 118.8
    brief.intent.preferences.max_walk_km = 1
    brief.intent.preferences.low_crowd = True
    plan = candidates(brief)
    assert len(plan.tasks) == 4
    assert any('距离偏好' in t.score.adjustments for t in plan.tasks)
    assert all(t.crowd.level == 'UNKNOWN' for t in plan.tasks)


def test_category_permutation_has_identical_scores_and_advice(brief):
    outcomes = []
    for categories in (['cityscape','architecture','humanities'], ['humanities','architecture','cityscape']):
        brief.intent = PhotographyIntent(categories=categories)
        ledger = Ledger()
        spots, _ = seed_spots(brief, ledger)
        solar = solar_windows(brief, spots[0].camera, ledger)
        value = score(brief, seed_conditions(brief, ledger)[14], datetime(2026,10,3,6,tzinfo=UTC), solar, ledger,0)
        outcomes.append((brief.intent.categories, value.weights, value.suitability, camera_advice(brief,0,ledger)))
    assert outcomes[0] == outcomes[1]
    assert 'genre' not in brief.model_dump() and 'profile' not in brief.model_dump()


async def test_description_overrides_defaults_but_preserves_manual_fields(brief,settings):
    network=Providers(settings)
    brief.text='明天想在南京拍电影感的湖面倒影，不想走太远。'
    brief.destination='苏州'
    try:
        book=await parse_description(brief,network)
        assert book.brief.destination=='南京'
        assert book.brief.travel_date != brief.travel_date
        assert book.brief.start_local==brief.start_local
        assert {'电影感','湖面倒影','低步行量'} <= set(book.recognized)
        assert book.brief.intent.preferences.strict==[]
        brief.edited_fields=['destination','travel_date']
        manual=await parse_description(brief,network)
        assert manual.brief.destination=='苏州' and manual.brief.travel_date==brief.travel_date
    finally:
        await network.client.aclose()


async def test_model_extraction_requires_literal_evidence_and_is_cached(brief,settings,respx_mock):
    settings.dashscope_api_key=SecretStr('intent-test-secret')
    brief.mode='live'
    brief.text='我要复古街头感，带宠物拍照。'
    import json
    raw={'fields':{'styles':['复古街头感'],'other_requirements':['带宠物拍照'],'destination':'北京'},
         'evidence':{'styles':'复古街头感','other_requirements':'带宠物拍照','destination':'没有这段文字'}}
    route=respx_mock.post(settings.dashscope_native_base_url+'/services/aigc/multimodal-generation/generation').respond(200,json={'output':{'choices':[{'message':{'content':[{'text':json.dumps(raw)}]}}]}})
    network=Providers(settings)
    network.cache.items.clear()
    try:
        book=await parse_description(brief,network)
        again=await parse_description(brief,network)
    finally:
        await network.client.aclose()
    assert book.parser==again.parser=='model' and route.call_count==1
    assert book.brief.intent.other_requirements==['带宠物拍照']
    assert book.brief.destination==brief.destination
    assert 'intent-test-secret' not in book.model_dump_json()
    payload=json.loads(route.calls[0].request.content)
    assert payload['parameters']['enable_search'] is False


async def test_model_failure_falls_back_without_losing_raw_description(brief,settings,respx_mock):
    settings.dashscope_api_key=SecretStr('parser-unavailable')
    brief.mode='live'
    brief.text='明天在南京拍夕阳，不想买门票。'
    respx_mock.post(settings.dashscope_native_base_url+'/services/aigc/multimodal-generation/generation').respond(503)
    network=Providers(settings)
    try:
        book=await parse_description(brief,network)
    finally:
        await network.client.aclose()
    assert book.parser=='rules' and book.brief.text==brief.text
    assert book.brief.intent.light=='golden_hour' and book.brief.intent.preferences.avoid_tickets


async def test_malformed_model_fields_preserve_other_valid_requests(brief,settings,respx_mock):
    import json
    settings.dashscope_api_key=SecretStr('malformed-parser-test')
    brief.mode='live'
    brief.text='周末想在南京拍复古街头感，步行尽量少。'
    raw={'fields':{'travel_date':'next weekend','styles':['复古街头感'], 'preferences':{'max_walk_km':'nearby','avoid_tickets':True}},
         'evidence':{'travel_date':'周末','styles':'复古街头感','preferences':'步行尽量少'}}
    respx_mock.post(settings.dashscope_native_base_url+'/services/aigc/multimodal-generation/generation').respond(200,json={'output':{'choices':[{'message':{'content':[{'text':json.dumps(raw)}]}}]}})
    network=Providers(settings)
    network.cache.items.clear()
    try:
        book=await parse_description(brief,network)
    finally:
        await network.client.aclose()
    assert book.brief.destination=='南京' and book.brief.travel_date==brief.travel_date
    assert '复古街头感' in book.brief.intent.styles
    assert any('travel_date' in note for note in book.assumptions)
    assert any('max_walk_km' in note for note in book.assumptions)


async def test_preference_negation_is_not_an_implicit_filter(brief,settings):
    brief.text='不要求人少，不介意门票，步行距离不限。'
    network=Providers(settings)
    try:
        book=await parse_description(brief,network)
    finally:
        await network.client.aclose()
    preferences=book.brief.intent.preferences
    assert not preferences.low_crowd and not preferences.avoid_tickets
    assert preferences.max_walk_km is None and not preferences.strict


async def test_ambiguous_place_requires_choice_and_rejects_forged_coordinates(brief,settings,respx_mock):
    settings.amap_web_service_key=SecretStr('map-choice-test')
    brief.mode='live'
    brief.destination='鼓楼'
    respx_mock.get(settings.amap_base_url+'/v3/geocode/geo').respond(200,json={'status':'1','geocodes':[{'adcode':'320106','formatted_address':'南京市鼓楼区','city':'南京市','location':'118.8,32.05'}]})
    respx_mock.get(settings.amap_base_url+'/v3/place/text').respond(200,json={'status':'1','pois':[{'id':'B123','name':'鼓楼公园','cityname':'南京市','adcode':'320106','location':'118.78,32.05'},{'id':'B456','name':'鼓楼','cityname':'徐州市','adcode':'320302','location':'117.18,34.28'}]})
    network=Providers(settings)
    network.cache.items.clear()
    try:
        book=await resolve_notebook(notebook(brief),network)
        assert book.location_status=='needs_choice' and len(book.location_choices)==3
        brief.location=book.location_choices[1]
        confirmed=await resolve_notebook(notebook(brief),network)
        assert confirmed.location_status=='confirmed'
        assert confirmed.brief.location.poi_id=='B123' and confirmed.brief.location.adcode=='320106'
        brief.location.lat=80
        rejected=await resolve_notebook(notebook(brief),network)
        assert rejected.location_status=='needs_choice' and rejected.brief.location is None
    finally:
        await network.client.aclose()


def test_ambiguous_research_returns_choices_without_creating_job(brief,settings,monkeypatch):
    brief.mode='live'
    brief.destination='老街'
    async def resolve(book,network):
        book.location_status='needs_choice'
        return book
    monkeypatch.setattr('backend.app.main.resolve_notebook',resolve)
    with TestClient(create_app(settings)) as client:
        result=client.post('/v1/photo-research',json=brief.model_dump(mode='json'))
        assert result.json()['status']=='needs_clarification'
        assert not client.get('/v1/plans').json()

@pytest.mark.parametrize('description,start,day', [('明天在南京拍建筑','00:00','2026-09-13'),('今天在南京拍建筑','15:32','2026-09-12')])
async def test_description_date_updates_only_automatic_times(brief,settings,monkeypatch,description,start,day):
    from datetime import date, time
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls,tz=None):
            return datetime(2026,9,12,7,32,45,tzinfo=UTC).astimezone(tz)
    monkeypatch.setattr('backend.app.intent_parser.datetime',FrozenDateTime)
    brief.travel_date=date(2026,9,12)
    brief.end_date=brief.travel_date
    brief.start_local=time(10)
    brief.end_local=time(23,59)
    brief.auto_time_fields=['start_local','end_local','end_date']
    brief.text=description
    network=Providers(settings)
    try:
        book=await parse_description(brief,network)
    finally:
        await network.client.aclose()
    assert str(book.brief.travel_date)==day
    assert book.brief.start_local.strftime('%H:%M')==start
    assert book.brief.end_local==time(23,59)
    assert book.brief.end_date==book.brief.travel_date
    assert book.brief.auto_time_fields==brief.auto_time_fields


async def test_model_explicit_times_take_ownership_from_defaults(brief,settings,respx_mock):
    import json
    from datetime import time
    settings.dashscope_api_key=SecretStr('explicit-time-test')
    brief.mode='live'
    brief.auto_time_fields=['start_local','end_local','end_date']
    brief.text='明天想拍建筑，16:00到19:00。'
    raw={'fields':{'start_local':'16:00','end_local':'19:00'},'evidence':{'start_local':'16:00','end_local':'19:00'}}
    respx_mock.post(settings.dashscope_native_base_url+'/services/aigc/multimodal-generation/generation').respond(200,json={'output':{'choices':[{'message':{'content':[{'text':json.dumps(raw)}]}}]}})
    network=Providers(settings)
    network.cache.items.clear()
    try:
        book=await parse_description(brief,network)
    finally:
        await network.client.aclose()
    assert book.brief.start_local==time(16) and book.brief.end_local==time(19)
    assert book.brief.auto_time_fields==['end_date']


async def test_manual_times_are_preserved_when_description_changes_date(brief,settings):
    original_start,original_end=brief.start_local,brief.end_local
    brief.auto_time_fields=['end_date']
    brief.edited_fields=['start_local','end_local']
    brief.text='明天在南京拍建筑'
    network=Providers(settings)
    try:
        book=await parse_description(brief,network)
    finally:
        await network.client.aclose()
    assert book.brief.start_local==original_start and book.brief.end_local==original_end
    assert book.brief.end_date==book.brief.travel_date
