import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.app.engine import Ledger
from backend.app.main import create_app
from backend.app.models import Position, ReferenceSearch, ReverseContext, TripBrief
from backend.app.providers import Providers
from backend.app.reference_locator import (
    broad_administrative_area,
    locate_original,
    map_anchor_candidates,
    relation_check,
)
from backend.app.vision import VisualAnalysis


def visual():
    return VisualAnalysis(summary='城墙与高楼',subjects=['高楼'],hypotheses=[{
        'name':'解放门城墙段','anchor_poi':'解放门','city':'南京市',
        'reason':'城墙走向与远处建筑的层次相符','confidence':'high','camera_instruction':'城墙步道，入口待确认'}])


class Network:
    def __init__(self,mapped=False,web=False):
        self.mapped=mapped
        self.web=web
        self.queries=[]
        self.poi_calls=[]

    async def search(self,brief,purpose,*,reference,reference_context=None):
        assert reference and isinstance(brief, TripBrief) and brief.travel_date is None
        assert brief.sensor == 'full_frame' and brief.lenses == [] and brief.start_local is None
        assert brief.text == ''
        assert reference_context and reference_context['visual_analysis']['hypotheses']
        self.queries.append(reference_context)
        if not self.web:
            raise TimeoutError()
        return {'candidates':[{'name':'解放门城墙段','camera_poi':'解放门','composition':'城墙取景',
                               'source_indices':[1,999]}],
                'sources':[{'index':1,'url':'https://www.example.com/photography','title':'城市取景笔记'}]}

    async def poi(self,name,city):
        self.poi_calls.append((name,city))
        if not self.mapped:
            raise ValueError('ambiguous')
        return {'id':'B-test','name':name,'adcode':'320102','location':'118.8,32.06','photos':[]}


async def test_correct_visual_hypothesis_survives_web_and_map_failure():
    net=Network()
    candidates,spots,claims=await locate_original(visual(),ReferenceSearch(notes='原图来自朋友'),net,Ledger(),{},[])
    assert len(candidates)==1 and not spots
    assert candidates[0].name=='解放门城墙段' and candidates[0].spot_id is None
    assert candidates[0].status=='possible' and len(candidates[0].missing)==2
    assert net.queries[0]['notes']=='原图来自朋友'
    assert net.queries[0]['visual_analysis']['hypotheses'][0]['name']=='解放门城墙段'
    assert not claims


async def test_map_existence_alone_is_not_original_identity():
    candidates,spots,_=await locate_original(visual(),ReferenceSearch(),Network(mapped=True),Ledger(),{},[])
    assert spots and candidates[0].status=='possible'
    assert spots[0].camera.precision=='MAP_POINT'


async def test_title_does_not_drop_agent_candidate_and_fake_indices_are_ignored():
    ledger=Ledger()
    net=Network(mapped=True,web=True)
    candidates,spots,claims=await locate_original(visual(),ReferenceSearch(),net,ledger,{},[])
    assert len(candidates)==len(spots)==1
    assert candidates[0].status=='high_inference'
    assert len(candidates[0].source_ids)==len(claims)==1
    assert net.poi_calls==[('解放门','南京市')]
    assert set(candidates[0].evidence_ids)<={e.id for e in ledger.evidence}
    assert all(c.source_id in {s.id for s in ledger.sources} for c in claims)


def point(lat,lon):
    return Position(lat=lat,lon=lon,evidence_ids=['test'])


def test_geometry_handles_wraparound_overlap_and_uncertainty():
    camera=point(30,120)
    left,right=point(31,119.9),point(31,120.1)
    assert relation_check(camera,left,right,'left_of')['result']=='supports'
    assert relation_check(camera,right,left,'left_of')['result']=='conflicts'
    assert relation_check(camera,point(31,120),point(32,120),'overlaps')['result']=='supports'
    assert relation_check(camera,camera,right,'left_of')['result']=='unknown'


def test_unrecognized_visual_light_does_not_erase_correct_location():
    data=visual().model_dump()
    data['light']='soft_overcast'
    parsed=VisualAnalysis.model_validate(data)
    assert parsed.light=='any' and parsed.difficulties
    assert parsed.hypotheses[0].name=='解放门城墙段'


async def test_gps_contradiction_downgrades_but_keeps_candidate():
    candidates,spots,_=await locate_original(visual(),ReferenceSearch(),Network(mapped=True,web=True),Ledger(),
        {'gps':{'lat':40,'lon':116}},[])
    assert spots and candidates[0].status=='possible' and candidates[0].conflicts


async def test_same_named_camera_anchor_in_different_cities_is_not_merged():
    net=Network(mapped=True,web=True)
    base=net.search
    async def search(*args,**kwargs):
        result=await base(*args,**kwargs)
        result['candidates'][0]['city']='其他市'
        return result
    net.search=search
    candidates,spots,_=await locate_original(visual(),ReferenceSearch(),net,Ledger(),{},[])
    assert len(candidates)==len(spots)==2
    assert {c.city for c in candidates}=={'南京市','其他市'}


async def test_parent_area_fallback_is_explicit_and_not_high_confidence():
    v=visual()
    v.hypotheses[0].place_name='城墙景区'
    net=Network(mapped=True)
    original=net.poi
    async def poi(name,city):
        if name=='解放门':
            raise ValueError('ambiguous')
        return await original(name,city)
    net.poi=poi
    candidates,spots,_=await locate_original(v,ReferenceSearch(),net,Ledger(),{},[])
    assert spots[0].camera.precision=='AREA'
    assert candidates[0].status=='possible' and any('所属区域' in m for m in candidates[0].missing)


async def test_administrative_district_never_replaces_failed_camera_anchor():
    v=visual()
    v.hypotheses[0].anchor_poi='不存在的精确城墙段'
    v.hypotheses[0].place_name='玄武区'
    net=Network(mapped=False)
    async def poi(name,city):
        net.poi_calls.append((name,city))
        if name=='玄武区':
            return {'id':'district','name':'玄武区','adcode':'320102','location':'118.8,32.06','photos':[]}
        if not net.mapped:
            raise ValueError('ambiguous')
    net.poi=poi
    candidates,spots,_=await locate_original(v,ReferenceSearch(),net,Ledger(),{},[])
    assert not spots and candidates[0].spot_id is None
    assert ('玄武区','南京市') not in net.poi_calls
    assert any('行政区' in message for message in candidates[0].missing)


async def test_agent_coordinate_is_displayed_when_amap_cannot_match():
    v=visual()
    v.hypotheses[0].anchor_poi='明城墙台城景区'
    v.hypotheses[0].place_name='玄武区'
    net=Network(web=True)
    async def search(brief,purpose,*,reference,reference_context=None):
        assert reference and reference_context
        return {'sources':[],'candidates':[{
            'display_name':'南京明城墙台城段（解放门附近）',
            'name':'南京明城墙台城段（解放门附近）','city':'南京市',
            'visual_hypothesis_index':0,
            'camera_location':{'display_name':'南京明城墙台城段','map_anchor':'无法唯一匹配的台城段',
                'coordinate':{'lat':32.0682,'lon':118.7965,'crs':'WGS84',
                              'basis':'inference','source_index':None,'note':'台城景区近似中心'}},
            'place_name':'玄武区','camera_instruction':'在公开城墙步道寻找角度',
            'subject_locations':[{'display_name':'鸡鸣寺','map_anchor':'鸡鸣寺'}],
            'composition':'长焦压缩古今建筑','source_indices':[]}]}
    async def poi(name,city):
        net.poi_calls.append((name,city))
        raise ValueError('ambiguous')
    net.search=search
    net.poi=poi
    candidates,spots,_=await locate_original(v,ReferenceSearch(),net,Ledger(),{},[])
    assert spots and spots[0].camera.precision=='APPROXIMATE'
    assert spots[0].camera.lat==32.0682 and spots[0].camera.lon==118.7965
    assert candidates[0].location_status=='estimated' and candidates[0].spot_id
    assert candidates[0].camera_position==spots[0].camera
    assert any('采用推测坐标' in message for message in candidates[0].support)


async def test_web_agent_map_anchor_refines_the_matching_visual_hypothesis():
    v=visual()
    v.hypotheses[0].anchor_poi='南京明城墙难以解析的路段名'
    v.hypotheses[0].place_name='玄武区'
    net=Network(web=True)
    async def poi(name,city):
        net.poi_calls.append((name,city))
        if name!='解放门':
            raise ValueError('ambiguous')
        return {'id':'gate','name':'南京城墙景区-解放门','adcode':'320102','location':'118.8,32.06','photos':[]}
    net.poi=poi
    candidates,spots,_=await locate_original(v,ReferenceSearch(),net,Ledger(),{},[])
    assert spots and net.poi_calls[0]==('解放门','南京市')
    assert any('高德使用锚点 解放门' in message for message in candidates[0].support)


async def test_detailed_visual_analysis_uses_unbounded_reference_context():
    v=visual().model_copy(update={
        'summary':'详细画面描述'*140,
        'composition':'详细构图关系'*100,
        'styles':['长焦压缩','古今同框','城市风光'],
        'subjects':['紫峰大厦','鸡鸣寺药师佛塔','南京明城墙'],
    })
    assert len(v.model_dump_json()) > 1500
    net=Network(mapped=True)
    candidates,spots,_=await locate_original(v,ReferenceSearch(region_hint='南京'),net,Ledger(),{},[])
    assert candidates and spots
    assert len(json.dumps(net.queries[0]['visual_analysis'],ensure_ascii=False)) > 1500


async def test_live_reference_pipeline_reaches_search_agent_with_complete_contract(settings, respx_mock):
    settings.dashscope_api_key=SecretStr('reference-search-contract')
    settings.amap_web_service_key=SecretStr('reference-map-contract')
    agent_result={'candidates':[{'display_name':'解放门城墙段','name':'解放门城墙段','city':'南京市',
        'visual_hypothesis_index':0,'camera_location':{'display_name':'解放门城墙段','map_anchor':'解放门',
            'coordinate':{'lat':32.06,'lon':118.8,'crs':'WGS84','basis':'source',
                          'source_index':1,'note':'来源提供的位置'}},
        'place_name':'南京城墙景区','composition':'城墙走向与画面相符','source_indices':[1]}]}
    frame={'output':{'search_info':{'search_results':[{'index':1,'url':'https://example.com/nanjing-wall',
        'title':'南京解放门城墙摄影机位'}]},'choices':[{'message':{'content':[{'text':json.dumps(agent_result,ensure_ascii=False)}]}}]}}
    agent_route=respx_mock.post(settings.dashscope_native_base_url+'/services/aigc/multimodal-generation/generation').mock(
        return_value=httpx.Response(200,text='data: '+json.dumps(frame,ensure_ascii=False)+'\n\n'))
    map_route=respx_mock.get(settings.amap_base_url+'/v3/place/text').respond(200,json={'status':'1','pois':[
        {'id':'gate','name':'解放门','adcode':'320102','location':'118.8,32.06','photos':[]}]})
    network=Providers(settings)
    network.cache.items.clear()
    warnings=[]
    try:
        candidates,spots,_=await locate_original(visual(),ReferenceSearch(notes='核对台城段'),network,Ledger(),{},warnings)
    finally:
        await network.client.aclose()
    assert agent_route.call_count==1 and map_route.call_count>=1
    assert spots and candidates[0].spot_id and candidates[0].source_ids
    assert not any('联网证据暂不可用' in warning for warning in warnings)


def test_reference_map_anchor_helpers_keep_specific_places_only():
    assert broad_administrative_area('玄武区')
    assert not broad_administrative_area('台城景区')
    anchors=map_anchor_candidates(['南京明城墙解放门段 / 台城观景台'],'南京市')
    assert anchors==['南京明城墙解放门段','明城墙解放门段','台城观景台']
    assert '解放门' not in anchors and '玄武区' not in anchors


def test_identification_api_excludes_planning_fields(settings):
    schema=ReferenceSearch.model_json_schema()
    assert set(schema['properties'])=={'region_hint','notes','data_mode'}
    for field,value in [('mode','similar'),('days',3),('travel_date','2027-01-01'),('brief',{})]:
        with pytest.raises(ValueError):
            ReferenceSearch.model_validate({field:value})
    with pytest.raises(ValueError):
        ReverseContext(analysis_id='a'*32,spot_id='x',days=3)
    with TestClient(create_app(settings)) as client:
        response=client.post('/v1/reference-photos/'+'a'*32+'/analysis',json={'days':3})
        assert response.status_code==422


async def test_verified_scope_requires_independent_geometry_and_gps():
    from backend.app.providers import gcj_to_wgs
    v=visual()
    h=v.hypotheses[0]
    h.landmarks=['左楼','中楼','右楼']
    from backend.app.vision import LandmarkRelation
    first=LandmarkRelation(first='左楼',second='中楼',relation='left_of')
    second=LandmarkRelation(first='中楼',second='右楼',relation='left_of')
    h.relations=[first,second]
    net=Network()
    async def poi(name,city):
        coordinates={'解放门':'118.8,32.06','左楼':'118.7,32.16','中楼':'118.8,32.16','右楼':'118.9,32.16'}
        return {'id':name,'name':name,'location':coordinates[name],'photos':[]}
    net.poi=poi
    lon,lat=gcj_to_wgs(118.8,32.06)
    gps={'gps':{'lat':lat,'lon':lon}}
    candidates,_,_=await locate_original(v,ReferenceSearch(),net,Ledger(),gps,[])
    assert candidates[0].status=='verified'
    assert '未鉴定原片' in candidates[0].verification_scope
    h.relations=[first,first]
    candidates,_,_=await locate_original(v,ReferenceSearch(),net,Ledger(),gps,[])
    assert candidates[0].status!='verified' and len(candidates[0].geometry)==1


def test_historical_reference_plan_remains_readable(plan):
    from backend.app.models import ShotPlan
    value=plan.model_dump(mode='json')
    value['brief']['reverse_context']={'analysis_id':'a'*32,'spot_id':plan.spots[0].id,'days':3}
    restored=ShotPlan.model_validate(value)
    assert 'days' not in restored.brief.reverse_context.model_dump()
