"""Original-camera hypotheses survive incomplete evidence; only providers supply coordinates."""
import asyncio
import hashlib
import logging
import re
import time
from typing import Literal

from pydantic import Field

from .discovery import AMapPhotos
from .engine import bearing
from .models import Model, PhotoSpot, PlaceEntity, Position, SourceClaim, Subject, TripBrief, TruthLabel
from .providers import ProviderError, canonical_url, gcj_to_wgs
from .recommendations import distance_km

logger = logging.getLogger(__name__)


class ReferenceCandidate(Model):
    id: str
    name: str
    city: str = ''
    camera_instruction: str = ''
    reason: str = ''
    status: Literal['verified', 'high_inference', 'possible'] = 'possible'
    score: int = 0
    spot_id: str | None = None
    location_status: Literal['mapped', 'area', 'estimated', 'unlocated'] = 'unlocated'
    camera_position: Position | None = None
    support: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    geometry: list[dict] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    verification_scope: str = '原片身份尚未独立确认；评分为证据排序分，不是概率。'


def broad_administrative_area(name):
    """Administrative centroids are not camera locations."""
    value = re.sub(r"[\s（）()]", "", name or "")
    if value.endswith(("景区", "街区", "园区", "校区", "社区")):
        return False
    return bool(re.search(r"(?:省|自治区|市|自治州|盟|区|县|自治县|旗|镇|乡|街道)$", value))


def map_anchor_candidates(anchors, city):
    """Try Agent-provided anchors without landmark-specific rewrite rules."""
    values = []
    city_names = [city, city.removesuffix("市")] if city else []
    for raw in anchors:
        for part in re.split(r"[/／|]", raw or ""):
            value = part.strip(" ，,、")
            if not value:
                continue
            variants = [value]
            without_city = value
            for city_name in city_names:
                if city_name and without_city.startswith(city_name):
                    without_city = without_city[len(city_name):]
                    break
            variants.append(without_city)
            for candidate in variants:
                candidate = candidate.strip(" -—·，,、")
                if len(candidate) >= 2 and candidate not in values and not broad_administrative_area(candidate):
                    values.append(candidate)
    return values


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
        anchor = h.anchor_poi or h.name
        rows.append({'name':h.name,'city':h.city or request.region_hint,'anchor':anchor,
                     'anchors':[anchor] if h.anchor_poi else [h.name],'place':h.place_name,
                     'instruction':h.camera_instruction,'reason':h.reason,'confidence':h.confidence,
                     'landmarks':h.landmarks,'relations':h.relations,'refs':[],'coordinate':None})
    # One shared search call: all visual hypotheses and the original user clue reach the Agent.
    city=' / '.join(dict.fromkeys(r['city'] for r in rows if r['city'])) or request.region_hint
    # Reference-image analysis is intentionally passed through a dedicated
    # context channel. TripBrief.text is a bounded user-input field and can be
    # much shorter than a valid, detailed VisualAnalysis payload.
    query=TripBrief(destination=city,intent=visual.intent(),mode='live')
    reference_context={
        'visual_analysis':visual.model_dump(mode='json'),
        'region_hint':request.region_hint,
        'notes':request.notes,
    }
    try:
        result=await network.search(query,'验证原照片的具体相机站位，保留缺少证据的合理候选',
            reference=True,reference_context=reference_context)
        sources={s.get('index'):s for s in result['sources']}
        for raw in result['candidates']:
            location=raw.get('camera_location') or {}
            display_name=raw.get('display_name') or raw.get('name') or location.get('display_name')
            anchor=location.get('map_anchor') or raw.get('camera_poi') or display_name
            hypothesis_index=raw.get('visual_hypothesis_index')
            matches=([rows[hypothesis_index]] if isinstance(hypothesis_index,int) and hypothesis_index<len(rows) else
                [r for r in rows if (r['name']==display_name or r['anchor']==anchor)
                     and (not raw.get('city') or r['city'].removesuffix('市')==raw['city'].removesuffix('市'))]
            )
            # Never assign a multi-city Web result to an arbitrary first city.
            matched=matches[0] if len(matches)==1 else None
            if matched is None:
                if len(rows)>=7:
                    continue
                matched={'name':display_name,'city':raw.get('city') or (city if ' / ' not in city else ''), 'anchor':anchor,
                         'anchors':[anchor], 'place':raw.get('place_name',''),
                         'instruction':raw.get('camera_instruction',''),'reason':raw['composition'],
                         'confidence':'low','landmarks':[item['map_anchor'] for item in raw.get('subject_locations',[])] or
                         ([raw['subject_poi']] if raw.get('subject_poi') else []),'relations':[],'refs':[],
                         'coordinate':location.get('coordinate')}
                rows.append(matched)
            else:
                # The web-search Agent is explicitly asked for an AMap-friendly
                # camera_poi. Prefer it without discarding the visual hypothesis.
                matched['anchor'] = anchor
                matched['anchors'] = list(dict.fromkeys([anchor, *matched.get('anchors', [])]))
                matched['name'] = display_name or matched['name']
                matched['place'] = raw.get('place_name') or matched.get('place', '')
                matched['instruction'] = raw.get('camera_instruction') or matched.get('instruction', '')
                matched['coordinate'] = location.get('coordinate') or matched.get('coordinate')
                for subject in raw.get('subject_locations',[]):
                    if subject.get('map_anchor') and subject['map_anchor'] not in matched['landmarks']:
                        matched['landmarks'].append(subject['map_anchor'])
                if raw.get('subject_poi') and raw['subject_poi'] not in matched['landmarks']:
                    matched['landmarks'].append(raw['subject_poi'])
            matched['refs'] += [sources[i] for i in raw['source_indices'] if i in sources]
    except ProviderError as error:
        logger.warning("Reference search unavailable: %s", error.code)
        warnings.append('联网证据暂不可用，保留视觉机位推断并降低置信等级。')
    except TimeoutError:
        logger.warning("Reference search unavailable: timeout")
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
        mapped = None
        mapped_anchor = ''
        for anchor in map_anchor_candidates(row.get('anchors', [row['anchor']]), row['city']):
            mapped = await resolve(anchor, row['city'])
            if mapped:
                mapped_anchor = anchor
                break
        area=False
        if not mapped and row.get('place') and row['place'] != row['anchor'] and not broad_administrative_area(row['place']):
            mapped=await resolve(row['place'],row['city'])
            area=bool(mapped)
            mapped_anchor = row['place'] if mapped else ''
        elif not mapped and broad_administrative_area(row.get('place', '')):
            candidate.missing.append('所属位置仅到行政区级别，不使用行政区中心代替相机机位')
        estimated=False
        if not mapped and row.get('coordinate'):
            coordinate=row['coordinate']
            lon,lat=float(coordinate['lon']),float(coordinate['lat'])
            if coordinate['crs']=='GCJ02':
                lon,lat=gcj_to_wgs(lon,lat)
            identity='agent-coordinate-'+hashlib.sha256(
                f"{row['name']}|{lat}|{lon}".encode()).hexdigest()[:16]
            ids=ledger.add(identity,'原机位坐标推测',TruthLabel.INFERRED,
                '高德未唯一匹配时的地图展示回退；不是高德 POI、实测 GPS 或精确相机站位。',
                {'lat':lat,'lon':lon,'crs':'WGS84','input_crs':coordinate['crs'],
                 'basis':coordinate['basis'],'note':coordinate.get('note','')})
            position=Position(lat=lat,lon=lon,precision='APPROXIMATE',evidence_ids=ids)
            mapped=({'id':identity,'name':row['name'],'photos':[]},position)
            mapped_anchor=row['anchor']
            estimated=True
        if mapped:
            poi,position=mapped
            if area:
                position=position.model_copy(update={'precision':'AREA'})
                candidate.missing.append('仅匹配所属区域；该坐标不能代表推断路段或相机位置')
            candidate.spot_id=candidate.id
            candidate.location_status='estimated' if estimated else 'area' if area else 'mapped'
            candidate.camera_position=position
            candidate.score+=3 if estimated else 5 if area else 15
            candidate.evidence_ids+=position.evidence_ids
            if estimated:
                candidate.support.append('高德未唯一匹配；采用推测坐标绘图，精确站位待确认')
                candidate.missing.append('坐标未经高德或实测 GPS 核验，只能作为搜索范围起点')
            else:
                candidate.support.append('高德使用锚点 '+mapped_anchor+' 匹配到 '+poi['name']+'；精确站位仍待确认')
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
                risks=[('推测坐标不是高德 POI 或精确站位；仅用于地图展示和现场搜索。' if estimated else
                        '原始机位尚待确认；地图点不是精确站位，不能据此保证可进入。')],
                unsafe=any(word in row['name']+row['instruction'] for word in ['翻越','车道中央','道路中央','无护栏','铁路','施工区']),
                claim_ids=[c.id for c in claims if c.subject_id==candidate.id],
                photo_references=[] if estimated else AMapPhotos.from_poi(poi,ledger)))
            if not estimated and not area and not candidate.conflicts and candidate.score>=65 and (candidate.source_ids or candidate.geometry):
                candidate.status='high_inference'
            # 'verified' describes deterministic checks, never authenticated photo identity.
            if not estimated and not area and not candidate.conflicts and gps and distance<.3 and sum(g['result']=='supports' for g in candidate.geometry)>=2:
                candidate.status='verified'
                candidate.verification_scope='已核验地图、文件 GPS 邻近及多地标平面方位；仍未鉴定原片出处与精确站位。'
        else:
            candidate.missing.append('高德未唯一匹配，也没有可用推测坐标；保留文字机位推断')
        candidate.score=max(0,min(95,candidate.score))
        candidate.evidence_ids=list(dict.fromkeys(candidate.evidence_ids))
        candidates.append(candidate)
    candidates.sort(key=lambda c:c.score,reverse=True)
    return candidates,spots,claims
