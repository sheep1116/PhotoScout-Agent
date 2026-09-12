import pytest
from fastapi.testclient import TestClient

from backend.app.engine import Ledger
from backend.app.main import create_app
from backend.app.models import Position, ReferenceSearch, ReverseContext
from backend.app.reference_locator import locate_original, relation_check
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

    async def search(self,brief,purpose,*,reference):
        assert reference and brief.travel_date is None
        self.queries.append(brief.text)
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
    assert '原图来自朋友' in net.queries[0] and '城墙段' in net.queries[0]
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
