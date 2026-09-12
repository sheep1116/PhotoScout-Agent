"""Original-camera hypotheses survive incomplete evidence; only providers supply coordinates."""
import asyncio
import hashlib
import time
from types import SimpleNamespace
from typing import Literal

from pydantic import Field

from .discovery import AMapPhotos
from .engine import bearing
from .models import Model, PhotoSpot, PlaceEntity, Position, SourceClaim, Subject, TruthLabel
from .providers import canonical_url, gcj_to_wgs
from .recommendations import distance_km


class ReferenceCandidate(Model):
    id: str
    name: str
    city: str = ''
    camera_instruction: str = ''
    reason: str = ''
    status: Literal['verified', 'high_inference', 'possible'] = 'possible'
    score: int = 0
    spot_id: str | None = None
    support: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    geometry: list[dict] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    verification_scope: str = '原片身份尚未独立确认；评分为证据排序分，不是概率。'


def relation_check(camera, first, second, relation):
    """Angular consistency, not visibility, triangulation or exact camera recovery."""
    a, b = bearing(camera, first), bearing(camera, second)
    delta = (b-a+180) % 360-180
    near = min(distance_km(camera.lat,camera.lon,p.lat,p.lon) for p in (first,second)) < .1
    # Coarse POI centroids cannot robustly establish ordering near a boundary.
    uncertain = near or (relation == 'left_of' and (abs(delta)<3 or abs(delta)>177))
    consistent = 0<delta<180 if relation=='left_of' else abs(delta)<=3
    return {'first_bearing_deg':a,'second_bearing_deg':b,'separation_deg':round(abs(delta),1),
            'result':'unknown' if uncertain else 'supports' if consistent else 'conflicts',
            'note':'POI 中心的平面方位关系；未计算高度、遮挡，裁切或镜像可能影响判断。'}


async def locate_original(visual, request, network, ledger, exif, warnings):
    rows=[]
    for h in visual.hypotheses:
        rows.append({'name':h.name,'city':h.city or request.region_hint,'anchor':h.anchor_poi or h.name,'place':h.place_name,
                     'instruction':h.camera_instruction,'reason':h.reason,'confidence':h.confidence,
                     'landmarks':h.landmarks,'relations':h.relations,'refs':[]})
    # One shared search call: all visual hypotheses and the original user clue reach the Agent.
    city=' / '.join(dict.fromkeys(r['city'] for r in rows if r['city'])) or request.region_hint
    query=SimpleNamespace(destination=city,location=None,travel_date=None,intent=visual.intent(),
        text='参考画面与原机位假设：'+visual.model_dump_json()+'；用户地点线索：'+request.region_hint+'；补充：'+request.notes)
    try:
        result=await network.search(query,'验证原照片的具体相机站位，保留缺少证据的合理候选',reference=True)
        sources={s.get('index'):s for s in result['sources']}
        for raw in result['candidates']:
            anchor=raw.get('camera_poi') or raw['name']
            matches=[r for r in rows if (r['name']==raw['name'] or r['anchor']==anchor)
                     and (not raw.get('city') or r['city'].removesuffix('市')==raw['city'].removesuffix('市'))]
            # Never assign a multi-city Web result to an arbitrary first city.
            matched=matches[0] if len(matches)==1 else None
            if matched is None:
                if len(rows)>=7:
                    continue
                matched={'name':raw['name'],'city':raw.get('city') or (city if ' / ' not in city else ''), 'anchor':anchor,'place':raw.get('place_name',''),
                         'instruction':raw.get('camera_instruction',''),'reason':raw['composition'],
                         'confidence':'low','landmarks':[raw['subject_poi']] if raw.get('subject_poi') else [],'relations':[],'refs':[]}
                rows.append(matched)
            matched['refs'] += [sources[i] for i in raw['source_indices'] if i in sources]
    except Exception:
        warnings.append('联网证据暂不可用，保留视觉机位推断并降低置信等级。')

    memo={}
    deadline=time.monotonic()+45
    async def resolve(name, region):
        key=(name,region)
        if key not in memo:
            memo[key]=None
            if not name or not region or len(memo)>16 or time.monotonic()>=deadline:
                return None
            try:
                async with asyncio.timeout(min(8,max(.01,deadline-time.monotonic()))):
                    poi=await network.poi(name,region)
                x,y=gcj_to_wgs(*map(float,poi['location'].split(',')))
                ids=ledger.add('ref-map-'+hashlib.sha256(str(key).encode()).hexdigest()[:16],
                    '高德地点核验',TruthLabel.REPORTED,'地图地标中心，不是实测相机站位。',
                    {'poi_id':poi['id'],'adcode':poi.get('adcode'),'standard_name':poi['name'],'lat':y,'lon':x},
                    'https://www.amap.com/place/'+poi['id'])
                memo[key]=(poi,Position(lat=y,lon=x,precision='MAP_POINT',evidence_ids=ids))
            except Exception:
                pass
        return memo[key]

    spots=[]
    candidates=[]
    claims=[]
    for index,row in enumerate(rows):
        candidate=ReferenceCandidate(id=f'original-{index}',name=row['name'],city=row['city'],
            camera_instruction=row['instruction'],reason=row['reason'])
        candidate.evidence_ids=ledger.add(candidate.id+'-hypothesis','Agent 原机位推断',TruthLabel.INFERRED,
            row['reason'],{'name':row['name'],'camera_instruction':row['instruction']})
        candidate.score={'low':25,'medium':35,'high':45}[row['confidence']]
        for source in row['refs']:
            url=canonical_url(source.get('url',''))
            if not url:
                continue
            key='ref-web-'+hashlib.sha256(url.encode()).hexdigest()[:16]
            sid='src-'+key
            if sid in candidate.source_ids:
                continue
            ids=ledger.add(key,source.get('title') or '联网来源',TruthLabel.REPORTED,
                'Agent 将此真实搜索来源关联到机位；未逐句确认原文，不证明原片出处。',{'candidate':row['name']},url,kind='search')
            candidate.source_ids.append(sid)
            candidate.evidence_ids+=ids
            claims.append(SourceClaim(id=f'claim-{index}-{len(candidate.source_ids)}',source_id=sid,subject_id=candidate.id,
                kind='viewpoint',statement=row['reason'],evidence_ids=ids))
        if candidate.source_ids:
            candidate.score+=10
            candidate.support.append('Agent 找到相关网页线索（来源关联仍属模型判断）')
        else:
            candidate.missing.append('尚缺独立网页证据')
        mapped=await resolve(row['anchor'],row['city'])
        area=False
        if not mapped and row.get('place') and row['place']!=row['anchor']:
            mapped=await resolve(row['place'],row['city'])
            area=bool(mapped)
        if mapped:
            poi,position=mapped
            if area:
                position=position.model_copy(update={'precision':'AREA'})
                candidate.missing.append('仅匹配所属区域；该坐标不能代表推断路段或相机位置')
            candidate.spot_id=candidate.id
            candidate.score+=5 if area else 15
            candidate.evidence_ids+=position.evidence_ids
            candidate.support.append('高德匹配到 '+poi['name']+'；精确站位仍待确认')
            landmarks={}
            for name in row['landmarks'][:3]:
                target=await resolve(name,row['city'])
                if target and .1<distance_km(position.lat,position.lon,target[1].lat,target[1].lon)<80:
                    landmarks[name]=target[1]
            checked=set()
            for relation in row['relations']:
                key=(frozenset((relation.first,relation.second)),relation.relation)
                if key in checked or relation.first==relation.second:
                    continue
                checked.add(key)
                if relation.first not in landmarks or relation.second not in landmarks:
                    candidate.missing.append('多地标关系缺少唯一地图匹配：'+relation.first+' / '+relation.second)
                    continue
                check=relation_check(position,landmarks[relation.first],landmarks[relation.second],relation.relation)
                check.update(first=relation.first,second=relation.second,relation=relation.relation)
                candidate.geometry.append(check)
                ids=ledger.add(f'{candidate.id}-geometry-{len(candidate.geometry)}','地标方位计算',TruthLabel.CALCULATED,
                    check['note'],check)
                candidate.evidence_ids+=ids+landmarks[relation.first].evidence_ids+landmarks[relation.second].evidence_ids
                if check['result']=='supports':
                    candidate.score+=8
                    candidate.support.append('地标平面方位关系相符：'+relation.first+' / '+relation.second)
                elif check['result']=='conflicts':
                    candidate.score-=20
                    candidate.conflicts.append('地标方位存在矛盾：'+relation.first+' / '+relation.second)
            gps=exif.get('gps')
            if gps:
                distance=distance_km(gps['lat'],gps['lon'],position.lat,position.lon)
                ids=ledger.add(candidate.id+'-gps','EXIF 与地图距离',TruthLabel.CALCULATED,
                    'EXIF 可修改；距离相近不单独证明原片身份。',{'distance_km':distance})
                candidate.evidence_ids+=ids
                if distance<.3:
                    candidate.score+=15
                    candidate.support.append(f'距文件 GPS 约 {distance:.2f} km（记录未经鉴真）')
                elif distance>5:
                    candidate.score-=25
                    candidate.conflicts.append(f'距文件 GPS 约 {distance:.1f} km，需核对')
            access=ledger.add(candidate.id+'-access','开放待核实',TruthLabel.UNKNOWN,'机位识别不验证未来开放、安全或预约条件。')
            spots.append(PhotoSpot(id=candidate.id,name=row['name'],place=PlaceEntity(id=poi['id'],name=poi['name'],position=position),
                camera=position,camera_instruction=row['instruction'] or '地图地标附近，具体站位待确认',
                subjects=[Subject(name=n,position=p) for n,p in landmarks.items()] or [Subject(name=s) for s in visual.subjects[:3]],
                genres=visual.categories,composition=visual.composition,access_evidence_ids=access,
                risks=['原始机位尚待确认；地图点不是精确站位，不能据此保证可进入。'],
                unsafe=any(word in row['name']+row['instruction'] for word in ['翻越','车道中央','道路中央','无护栏','铁路','施工区']),
                claim_ids=[c.id for c in claims if c.subject_id==candidate.id],photo_references=AMapPhotos.from_poi(poi,ledger)))
            if not area and not candidate.conflicts and candidate.score>=65 and (candidate.source_ids or candidate.geometry):
                candidate.status='high_inference'
            # 'verified' describes deterministic checks, never authenticated photo identity.
            if not area and not candidate.conflicts and gps and distance<.3 and sum(g['result']=='supports' for g in candidate.geometry)>=2:
                candidate.status='verified'
                candidate.verification_scope='已核验地图、文件 GPS 邻近及多地标平面方位；仍未鉴定原片出处与精确站位。'
        else:
            candidate.missing.append('地图尚未唯一匹配；保留机位推断，不提供猜测坐标')
        candidate.score=max(0,min(95,candidate.score))
        candidate.evidence_ids=list(dict.fromkeys(candidate.evidence_ids))
        candidates.append(candidate)
    candidates.sort(key=lambda c:c.score,reverse=True)
    return candidates,spots,claims
