"""Explicit paid reverse-photo acceptance, using a previously verified public AMap image."""
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from backend.app.config import Settings
from backend.app.models import ShotPlan


def main(photo_id=None):
    settings=Settings()
    secrets=[k.get_secret_value() for k in (settings.dashscope_api_key,settings.amap_web_service_key) if k.get_secret_value()]
    with httpx.Client(base_url='http://127.0.0.1:3800/v1',timeout=60,trust_env=False) as client:
        def check(response):
            response.raise_for_status()
            if any(key in response.text for key in secrets):
                raise ValueError('secret detected')
            return response.json()
        prior=check(client.get('/plans/fbaf1dc11eec4d64aeef15287a0d0102'))
        image=next(p for s in prior['spots'] for p in s['photo_references'])
        if photo_id:
            photo=check(client.get('/reference-photos/'+photo_id))
        else:
            raw=client.get(f"/plans/{prior['id']}/photos/{image['id']}")
            raw.raise_for_status()
            photo=check(client.post('/reference-photos',content=raw.content,headers={'Content-Type':raw.headers['content-type']}))
        today=datetime.now(ZoneInfo('Asia/Shanghai')).date()
        brief={'destination':'南京市','travel_date':str(today+timedelta(days=1)),'end_date':str(today+timedelta(days=1)),
               'start_local':'00:00','end_local':'23:59','timezone':'Asia/Shanghai','mode':'live','text':'确认参考照片原机位后的复刻建议。',
               'intent':{'categories':['architecture']},'tripod':True,'lenses':[{'name':'24–70mm F4','min_mm':24,'max_mm':70,'max_aperture':4}]}
        started=check(client.post(f"/reference-photos/{photo['id']}/analysis",json={'region_hint':'南京市','data_mode':'live'}))
        identifier=started['research_id']
        print(json.dumps({'stage':'analysis_started','id':identifier}),flush=True)
        def wait(identifier):
            for _ in range(210):
                job=check(client.get('/photo-research/'+identifier))
                if job['status']=='failed':
                    raise ValueError('job_failed')
                if job['status']=='complete':
                    return
                time.sleep(1)
            raise TimeoutError()
        wait(identifier)
        analysis=check(client.get('/reference-analyses/'+identifier))
        if not analysis['spots']:
            raise ValueError('no_candidate')
        brief['reverse_context']={'analysis_id':identifier,'spot_id':analysis['spots'][0]['id']}
        job=check(client.post('/photo-research',json=brief))
        plan_id=job['research_id']
        print(json.dumps({'stage':'planning','id':plan_id,'candidates':len(analysis['spots'])}),flush=True)
        wait(plan_id)
        plan=ShotPlan.model_validate(check(client.get('/plans/'+plan_id)))
        checks={'vision_real':any(e.label=='INFERRED' and e.source_id.startswith('src-reference-vision') for e in plan.evidence),
                'has_candidates':bool(analysis['spots']),'one_confirmed_date':len(plan.recreation['windows'])==1,
                'identification_without_weather':analysis['metrics']['weather_calls']==0 and 'brief' not in analysis,
                'graded_candidates':all(c['status'] in ('verified','high_inference','possible') for c in analysis['candidates']),
                'real_forecast':any(w['weather']['label']=='REPORTED' for w in plan.recreation['windows']),
                'same_selected_spot':plan.tasks[0].spot_id==brief['reverse_context']['spot_id'],
                'no_second_search':plan.metrics['search_calls']==0,'no_itinerary':not plan.routes,
                'lens_constrained':all(24<=w['camera']['focal_mm']<=70 for w in plan.recreation['windows']),
                'uncertainty_visible':plan.recreation['location_confidence'] in ('possible','high_inference','verified'),
                'no_fixture':all(e.label!='FIXTURE' for e in plan.evidence),'schema_valid':True}
        report={'passed':all(checks.values()),'checks':checks,'photo_id':photo['id'],'analysis_id':identifier,'plan_id':plan_id,
                'image_source':image['source_url'],'visual':analysis['visual'],'candidate_count':len(analysis['candidates']),'mapped_count':len(analysis['spots']),'candidates':analysis['candidates'],
                'windows':len(plan.recreation['windows']),'metrics':plan.metrics,'warnings':analysis['warnings']}
        content=json.dumps(report,ensure_ascii=False,indent=2)
        if any(key in content for key in secrets):
            raise ValueError('secret in report')
        (Path('docs/verification')/'original-viewpoint-live.json').write_text(content,encoding='utf-8')
        print(json.dumps({'passed':report['passed'],'checks':checks,'plan_id':plan_id}),flush=True)
        return report['passed']


if __name__=='__main__':
    try:
        import argparse
        parser=argparse.ArgumentParser()
        parser.add_argument('--photo-id')
        success=main(parser.parse_args().photo_id)
    except Exception as error:
        print(json.dumps({'passed':False,'error_type':type(error).__name__}),flush=True)
        success=False
    raise SystemExit(0 if success else 1)
