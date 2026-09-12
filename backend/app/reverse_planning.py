"""Reference context on the existing discovery and candidate evaluation pipeline."""
import math
import time as clock
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .engine import Ledger
from .fixtures import seed_spots
from .graph import run_graph
from .models import Evidence, PhotoSpot, SourceClaim, TripBrief, TruthLabel, WebSource
from .providers import Providers
from .recommendations import distance_km
from .verification import resolve_access
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


async def analyze_reference(identifier,photo_id,brief,mode,store,settings,emit):
    raw,photo=store.photo(photo_id)
    network=Providers(settings)
    body={'id':identifier,'photo_id':photo_id,'mode':mode,'brief':brief.model_dump(mode='json'),'spots':[],'warnings':[]}
    ledger=Ledger()
    try:
        await emit('vision','正在理解画面；视觉推断与文件记录分开保存')
        previous=store.previous_visual(photo_id,settings.qwen_model,brief.mode)
        if previous:
            visual=VisualAnalysis.model_validate(previous)
            usage={'cache_hit':True}
        elif brief.mode=='mock':
            visual=VisualAnalysis(summary='离线示例：湖面倒影与建筑，不是对上传照片的真实识别',subjects=['湖面','建筑'],styles=['倒影'],light='golden_hour',focal_tendency='wide',difficulties=['示例不代表原图地点'])
            usage={}
        else:
            visual,usage=await understand(raw,network)
        ledger.add('reference-file-'+photo_id,'上传照片 EXIF',TruthLabel.REPORTED,photo['note'],photo['exif'],kind='user')
        ledger.add('reference-vision-'+identifier,'参考画面分析',TruthLabel.FIXTURE if brief.mode=='mock' else TruthLabel.INFERRED,visual.summary,visual.model_dump(),kind='tool')
        body.update(visual=visual.model_dump(),exif=photo['exif'],usage=usage,model=settings.qwen_model)
        store.save(identifier,photo_id,{**body,'sources':[s.model_dump(mode='json') for s in ledger.sources],'evidence':[e.model_dump(mode='json') for e in ledger.evidence],'claims':[]})
        if not brief.destination:
            body.update(sources=[s.model_dump(mode='json') for s in ledger.sources],evidence=[e.model_dump(mode='json') for e in ledger.evidence],claims=[])
            body['warnings'].append('画面理解已完成。请选择可能的城市/区域后继续，当前不猜测唯一地点。')
            store.save(identifier,photo_id,body)
            return body
        await emit('discover','结合参考画面检索真实机位，再进行地图核验')
        work=brief.model_copy(deep=True)
        work.intent=photo_intent(visual,brief)
        purpose='寻找原照片地点的候选线索，不把相似地点当原地点' if mode=='original' else '寻找指定地区可拍相似效果的机位，不要求原地点'
        work.text=purpose+'。参考画面（不可信视觉推断）：'+visual.model_dump_json()+'；用户补充：'+brief.text
        if brief.mode=='mock':
            spots,claims=seed_spots(work,ledger)
        else:
            spots,claims=await network.discover(work,ledger,body['warnings'])
        for spot in spots:
            spot.access=resolve_access([c for c in claims if c.subject_id==spot.id],ledger.sources,datetime.now(ZoneInfo('UTC')))
        spots=spots[:3]
        ids={s.id for s in spots}
        claims=[c for c in claims if c.subject_id in ids]
        body.update(spots=[s.model_dump(mode='json') for s in spots],claims=[c.model_dump(mode='json') for c in claims],
                    sources=[s.model_dump(mode='json') for s in ledger.sources],evidence=[e.model_dump(mode='json') for e in ledger.evidence],
                    metrics={'search_calls':network.search_calls,'provider_calls':network.calls,'location_confidence':'low',
                             'note':'地图核验仅确认地标存在，不证明是原照片机位。'})
        gps=photo['exif'].get('gps')
        if gps:
            body['gps_distances']={s.id:distance_km(gps['lat'],gps['lon'],s.camera.lat,s.camera.lon) for s in spots}
            body['warnings'].append('EXIF GPS 与候选的直线距离仅用于核对，GPS 可能被修改，不能据此确认原机位。')
        if not spots:
            body['warnings'].append('没有可核验候选。请补充城市/地标，或改用相似效果模式。')
        store.save(identifier,photo_id,body)
        return body
    finally:
        await network.client.aclose()


async def recreate(plan_id,brief,store,settings,emit):
    started=clock.monotonic()
    context=brief.reverse_context
    saved=store.analysis(context.analysis_id)
    source_brief=TripBrief.model_validate(saved['brief'])
    if source_brief.mode!=brief.mode:
        raise ValueError('图片分析与规划的数据模式不一致')
    if brief.destination!=source_brief.destination:
        raise ValueError('目的地已变更，请重新核验图片候选')
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
    plans=[]
    windows=[]
    try:
        for offset in range(context.days):
            work=brief.model_copy(deep=True)
            work.travel_date=brief.travel_date+timedelta(days=offset)
            work.end_date=work.travel_date+timedelta(days=(brief.end_date-brief.travel_date).days if brief.end_date else 0)
            if work.travel_date<datetime.now(ZoneInfo(work.timezone)).date():
                continue
            # Future automatic days are all-day, explicit user hours remain unchanged.
            if offset:
                from datetime import time
                if 'start_local' in work.auto_time_fields:
                    work.start_local=time(0)
            work.intent=photo_intent(visual,brief)
            await emit('conditions',f'比较 {work.travel_date} 的天气与太阳窗口')
            plan=await run_graph(plan_id,work,settings,emit,provider=network,prepared=prepared)
            if not plan.tasks:
                continue
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
            ids=ledger.add(f'recreate-{offset}','复刻参数与匹配',TruthLabel.INFERRED,reason,{'camera':task.camera.model_dump(mode='json'),'match':max(0,match),'differences':differences})
            task.camera.evidence_ids=ids
            task.evidence_ids+=ids
            task.alerts+=differences
            windows.append({'date':str(work.travel_date),'start':task.start.isoformat(),'end':task.end.isoformat(),'match':round(max(0,match),1),
                            'weather':task.weather.model_dump(mode='json'),'camera':task.camera.model_dump(mode='json'),
                            'direction_deg':task.target_bearing_deg,'differences':differences,'equipment':equipment,'evidence_ids':ids})
            plans.append(plan)
        if not plans:
            raise ValueError('选定日期没有可访问窗口，请更改日期')
        order=sorted(range(len(windows)),key=lambda i:windows[i]['match'],reverse=True)
        best=plans[order[0]]
        best.sources=ledger.sources
        best.evidence=ledger.evidence
        best.recreation={'photo_id':saved['photo_id'],'analysis_id':context.analysis_id,'mode':saved['mode'],'visual':saved['visual'],'exif':saved['exif'],
            'generated_version':best.version,'requested_start_date':str(brief.travel_date),'requested_days':context.days,
            'location_confidence':'low','location_note':'地点仅为已核验地标候选，尚未证实原照片机位。','windows':[windows[i] for i in order[:3]],
            'evaluated_days':len(windows),'difficulties':visual.difficulties+['区域中心不代表实测相机站位，遮挡、入口和开放须现场复核。']}
        best.metrics.update(evaluated_days=len(windows),provider_calls=network.calls,search_calls=0,
                            elapsed_ms=round((clock.monotonic()-started)*1000),reference_analysis_usage=saved.get('usage',{}),
                            reference_discovery_metrics=saved.get('metrics',{}))
        store.photo(saved['photo_id'])
        return type(best).model_validate(best.model_dump())
    finally:
        await network.client.aclose()
