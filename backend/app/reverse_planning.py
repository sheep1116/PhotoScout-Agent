"""Reference context on the existing discovery and candidate evaluation pipeline."""
import math
import time as clock

from .engine import Ledger
from .fixtures import seed_spots
from .graph import run_graph
from .models import Evidence, PhotoSpot, SourceClaim, TripBrief, TruthLabel, WebSource
from .providers import Providers
from .vision import VisualAnalysis, understand


def focal_target(visual,exif,sensor):
    value=exif.get('equivalent_mm')
    if isinstance(value,(int,float)) and 5<=value<=2000:
        return value,'EXIF 等效焦距（文件记录）'
    # Camera make alone is insufficient to establish crop factor.
    return {'wide':24,'normal':50,'tele':100,'unknown':35}[visual.focal_tendency], '视觉焦段倾向的试拍起点，未恢复原片焦距'


def photo_intent(visual,brief):
    intent=visual.intent()
    intent.preferences=brief.intent.preferences.model_copy(deep=True)
    intent.other_requirements=list(brief.intent.other_requirements)
    for field in ('categories','subjects','styles','light'):
        if field in brief.edited_fields or 'intent' in brief.edited_fields:
            setattr(intent,field,getattr(brief.intent,field))
    return intent


def nd_exposure(base_seconds,stops):
    if not 0 < base_seconds <= 3600 or not 0 <= stops <= 20:
        raise ValueError('曝光或 ND 档位超出范围')
    return base_seconds*2**stops


def field_of_view(focal_mm,sensor_width_mm):
    if focal_mm<=0 or sensor_width_mm<=0:
        raise ValueError('焦距和传感器宽度须大于零')
    return math.degrees(2*math.atan(sensor_width_mm/(2*focal_mm)))


async def analyze_reference(identifier,photo_id,request,store,settings,emit):
    from .reference_locator import ReferenceCandidate, locate_original
    raw,photo=store.photo(photo_id)
    network=Providers(settings)
    body={'id':identifier,'photo_id':photo_id,'request':request.model_dump(),'data_mode':request.data_mode,
          'vision_version':2,'spots':[],'candidates':[],'warnings':[]}
    ledger=Ledger()
    try:
        await emit('vision','正在理解地标与具体原始机位')
        previous=store.previous_visual(photo_id,settings.qwen_model,request.data_mode)
        if previous:
            visual=VisualAnalysis.model_validate(previous)
            usage={'cache_hit':True}
        elif request.data_mode=='mock':
            visual=VisualAnalysis(summary='离线示例：湖面倒影与建筑，不是对上传照片的真实识别',subjects=['湖面','建筑'],styles=['倒影'],light='golden_hour',focal_tendency='wide',difficulties=['示例不代表原图地点'])
            usage={}
        else:
            visual,usage=await understand(raw,network)
        ledger.add('reference-file-'+photo_id,'上传照片 EXIF',TruthLabel.REPORTED,photo['note'],photo['exif'],kind='user')
        ledger.add('reference-vision-'+identifier,'参考画面分析',TruthLabel.FIXTURE if request.data_mode=='mock' else TruthLabel.INFERRED,visual.summary,visual.model_dump(),kind='tool')
        body.update(visual=visual.model_dump(),exif=photo['exif'],usage=usage,model=settings.qwen_model)
        def save():
            body.update(sources=[s.model_dump(mode='json') for s in ledger.sources],evidence=[e.model_dump(mode='json') for e in ledger.evidence])
            store.save(identifier,photo_id,body)
        body['claims']=[]
        save()
        await emit('discover','Agent 收集原机位证据；地图与方位计算独立校验')
        if request.data_mode=='mock':
            work=TripBrief(destination='南京市',mode='mock',intent=visual.intent())
            spots,claims=seed_spots(work,ledger)
            spots=spots[:3]
            claims=[c for c in claims if c.subject_id in {s.id for s in spots}]
            candidates=[ReferenceCandidate(id=s.id,name=s.name,city='南京市',spot_id=s.id,camera_instruction=s.camera_instruction,
                reason='离线合成候选，不是对上传照片的定位',missing=['示例未经真实地图或网页核验']) for s in spots]
        else:
            candidates,spots,claims=await locate_original(visual,request,network,ledger,photo['exif'],body['warnings'])
        body.update(spots=[s.model_dump(mode='json') for s in spots],candidates=[c.model_dump() for c in candidates],
                    claims=[c.model_dump(mode='json') for c in claims],
                    metrics={'search_calls':network.search_calls,'provider_calls':network.calls,'weather_calls':0,
                             'note':'证据评分用于排序；地图匹配不等于原片机位鉴定。'})
        if not candidates:
            body['warnings'].append('画面暂缺足够定位线索，请补充可识别的城市、地标或原图出处后重试。')
        save()
        return body
    finally:
        await network.client.aclose()


async def recreate(plan_id,brief,store,settings,emit):
    started=clock.monotonic()
    context=brief.reverse_context
    saved=store.analysis(context.analysis_id)
    if saved['data_mode']!=brief.mode:
        raise ValueError('图片分析与规划的数据模式不一致')
    chosen=next((s for s in saved['spots'] if s['id']==context.spot_id),None)
    if chosen is None:
        raise ValueError('请先选择已验证的候选机位')
    spot=PhotoSpot.model_validate(chosen)
    visual=VisualAnalysis.model_validate(saved['visual'])
    ledger=Ledger()
    ledger.sources=[WebSource.model_validate(s) for s in saved['sources']]
    ledger.evidence=[Evidence.model_validate(e) for e in saved['evidence']]
    claims=[SourceClaim.model_validate(c) for c in saved['claims'] if c['subject_id']==spot.id]
    ledger.add('reference-selection','用户选择参考候选',TruthLabel.USER_CONFIRMED,'用户选择此候选进行复刻评估，不等于确认原始拍摄地点。',{'spot_id':spot.id})
    prepared={'ledger':ledger,'spots':[spot],'claims':claims,'warnings':saved['warnings'],'reference':{'weather':visual.weather}}
    network=Providers(settings)
    windows=[]
    try:
        work=brief.model_copy(deep=True)
        work.intent=photo_intent(visual,brief)
        await emit('conditions',f'评估 {work.travel_date} 的天气与太阳窗口')
        plan=await run_graph(plan_id,work,settings,emit,provider=network,prepared=prepared)
        if not plan.tasks:
            raise ValueError('所选时段没有可用拍摄窗口，请调整日期或时间')
        task=plan.tasks[0]
        target,reason=focal_target(visual,saved['exif'],work.sensor)
        crop={'full_frame':1,'aps_c':1.5,'m43':2,'phone':1}[work.sensor]
        lens=min(work.lenses,key=lambda item:abs(max(item.min_mm,min(item.max_mm,target/crop))*crop-target)) if work.lenses else None
        if lens:
            focal=max(lens.min_mm,min(lens.max_mm,target/crop))
            task.camera.lens=lens.name
            task.camera.focal_mm=round(focal,1)
            task.camera.equivalent_mm=round(focal*crop,1)
            task.camera.aperture=max(lens.max_aperture,task.camera.aperture)
            if not work.tripod:
                task.camera.shutter_seconds=min(task.camera.shutter_seconds,1/max(60,2*focal*crop))
        else:
            task.camera.lens='未指定镜头（画面目标起点）'
            task.camera.focal_mm=round(target/crop,1)
            task.camera.equivalent_mm=round(target,1)
            reason+='；请根据目标视角选择镜头'
        task.camera.adjustment=reason+'；'+task.camera.adjustment
        equipment=['参数为试拍起点，需现场测光，不保证原片曝光。']
        if visual.long_exposure:
            equipment.append('参考图疑似长曝光。建议三脚架；白天可考虑 ND，档位须按现场测光确定。')
            equipment.append(f'条件换算示例：若现场测光为 1/60 秒，加 6 档 ND 后约 {nd_exposure(1/60,6):.2f} 秒；不是原片参数。')
            if work.tripod and work.sensor!='phone':
                task.camera.shutter_seconds=max(task.camera.shutter_seconds,1)
                task.camera.iso=100
        if visual.filters or '倒影' in visual.styles:
            equipment.append('CPL 为可选，可能削弱想保留的水面倒影；不能从成片确认是否使用滤镜。')
        light_names={'any':'未知','daylight':'日间','sunrise':'日出','golden_hour':'黄金时刻','blue_hour':'蓝调','night':'夜间'}
        weather_names={'clear':'晴朗','overcast':'阴天','rain':'雨天','fog':'雾天','snow':'雪天','unknown':'未知'}
        differences=[f'参考光线：{light_names[visual.light]}（推断）；推荐窗口：{light_names.get(task.recommended_light,task.recommended_light)}。',
                     f'参考天气：{weather_names[visual.weather]}（推断）；未来预报云量 {task.weather.cloud_pct if task.weather.cloud_pct is not None else "未知"}%，降水 {task.weather.precipitation_mm if task.weather.precipitation_mm is not None else "未知"} mm。']
        match=task.score.suitability
        if visual.weather=='clear' and (task.weather.cloud_pct or 0)>70:
            differences.append('云量偏多，可能难以复刻清晰阳光和阴影。')
        ids=ledger.add('recreate-camera','复刻参数与匹配',TruthLabel.INFERRED,reason,{'camera':task.camera.model_dump(mode='json'),'match':max(0,match),'differences':differences})
        task.camera.evidence_ids=ids
        task.evidence_ids+=ids
        task.alerts+=differences
        windows.append({'date':str(work.travel_date),'start':task.start.isoformat(),'end':task.end.isoformat(),'match':round(max(0,match),1),
                        'weather':task.weather.model_dump(mode='json'),'camera':task.camera.model_dump(mode='json'),
                        'direction_deg':task.target_bearing_deg,'differences':differences,'equipment':equipment,'evidence_ids':ids})
        best=plan
        best.sources=ledger.sources
        best.evidence=ledger.evidence
        best.recreation={'photo_id':saved['photo_id'],'analysis_id':context.analysis_id,'visual':saved['visual'],'exif':saved['exif'],
            'generated_version':best.version,'requested_start_date':str(brief.travel_date),
            'location_confidence':next((c['status'] for c in saved['candidates'] if c['spot_id']==spot.id),'possible'),'location_note':'用户选择的原机位候选；地图点不证明精确相机位置。','windows':windows,
            'difficulties':visual.difficulties+['区域中心不代表实测相机站位，遮挡、入口和开放须现场复核。']}
        best.metrics.update(provider_calls=network.calls,search_calls=0,
                            elapsed_ms=round((clock.monotonic()-started)*1000),reference_analysis_usage=saved.get('usage',{}),
                            reference_discovery_metrics=saved.get('metrics',{}))
        store.photo(saved['photo_id'])
        return type(best).model_validate(best.model_dump())
    finally:
        await network.client.aclose()
