"""Explicit live acceptance: one description parse, place choice, bounded discovery."""
import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from backend.app.config import Settings
from backend.app.models import ShotPlan


def main():
    settings = Settings()
    secrets = [key.get_secret_value() for key in (settings.amap_web_service_key, settings.dashscope_api_key) if key.get_secret_value()]
    with httpx.Client(base_url="http://127.0.0.1:3800/v1", timeout=100, trust_env=False) as client:
        def call(path, body=None):
            response = client.get(path) if body is None else client.post(path, json=body)
            response.raise_for_status()
            if any(key in response.text for key in secrets):
                raise ValueError("SECRET_IN_RESPONSE")
            return response.json()
        today = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
        book = call('/notebook', {"destination": "南京市", "travel_date": today, "end_date": today,
            "start_local": "10:00", "end_local": "12:00", "timezone": "Asia/Shanghai", "mode": "live",
            "text": "明天想在鼓楼拍电影感的建筑、城市夜景和人文，不想走太远，不想买门票。傍晚16:00到19:00。",
            "intent": {"categories": ["landscape"]}, "lenses": [{"name": "35mm F1.8", "min_mm": 35, "max_mm": 35, "max_aperture": 1.8}]})
        if not book['location_choices']:
            print(json.dumps({'stage':'location_resolution','parser':book['parser'], 'location_status':book['location_status'], 'destination':book['brief']['destination'], 'questions':book['questions'], 'notes':book['assumptions']}, ensure_ascii=True), flush=True)
            raise ValueError('EXPECTED_DISAMBIGUATION_CHOICES')
        choice = next((c for c in book['location_choices'] if '南京' in c['city']), book['location_choices'][0])
        brief = book['brief']
        brief['location'] = choice
        confirmed = call('/destinations/resolve', brief)
        brief = confirmed['brief']
        result = call('/photo-research', brief)
        job_id = result['research_id']
        print(json.dumps({'status': 'started', 'research_id': job_id, 'parser': book['parser'], 'location_count': len(book['location_choices'])}), flush=True)
        deadline = time.monotonic()+200
        while time.monotonic() < deadline:
            result = call('/photo-research/'+job_id)
            if result['status'] in ('failed', 'complete'):
                break
            time.sleep(1)
        if result['status'] != 'complete':
            raise ValueError('DISCOVERY_DID_NOT_COMPLETE')
        plan = ShotPlan.model_validate(call('/plans/'+job_id))
        checks = {
            'model_parsing': book['parser']=='model',
            'description_destination_overrides_default': book['brief']['destination']=='鼓楼',
            'explicit_time_parsed': brief['start_local'].startswith('16:00') and brief['end_local'].startswith('19:00'),
            'all_equal_categories': plan.brief.intent.categories==['architecture','cityscape','humanities'],
            'soft_preferences': plan.brief.intent.preferences.avoid_tickets and plan.brief.intent.preferences.max_walk_km is not None and not plan.brief.intent.preferences.strict,
            'ambiguity_choices': len(book['location_choices'])>1,
            'stable_selected_location': plan.brief.location.id==choice['id'] and bool(plan.brief.location.adcode),
            'selected_record_confirmed': confirmed['location_status']=='confirmed',
            'raw_description_preserved': plan.brief.text==brief['text'],
            'candidate_result': plan.presentation=='candidates' and bool(plan.tasks) and not plan.routes,
            'no_profiles_or_primary_category': 'profile' not in plan.brief.model_dump() and 'genre' not in plan.brief.model_dump(),
            'no_fixture_evidence': all(e.label!='FIXTURE' for e in plan.evidence),
            'real_weather': all(t.weather.label=='REPORTED' for t in plan.tasks),
            'schema_integrity': True,
        }
        report={'passed': all(checks.values()), 'plan_id': job_id, 'checks': checks, 'parser':book['parser'],
                'recognized':book['recognized'], 'chosen_location':choice, 'metrics':plan.metrics,
                'candidate_count':len(plan.tasks), 'warnings':plan.warnings}
        folder=Path(__file__).resolve().parents[1]/'docs/verification'
        for name, content in [('discovery-agent-live.json', report), ('discovery-agent-plan.json', plan.model_dump(mode='json'))]:
            encoded=json.dumps(content,ensure_ascii=False,indent=2)
            if any(key in encoded for key in secrets):
                raise ValueError('SECRET_IN_ARTIFACT')
            (folder/name).write_text(encoded,encoding='utf-8')
        print(json.dumps({'passed':report['passed'],'checks':checks,'plan_id':job_id,'candidates':len(plan.tasks)},ensure_ascii=True),flush=True)
        return report['passed']


if __name__ == '__main__':
    try:
        ok=main()
    except Exception as error:
        print(json.dumps({'passed':False,'error_type':type(error).__name__}))
        ok=False
    raise SystemExit(0 if ok else 1)
