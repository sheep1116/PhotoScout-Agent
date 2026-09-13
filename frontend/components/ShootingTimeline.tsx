import {Clock3} from 'lucide-react';
import {localTime,Plan} from '@/lib/types';

export default function ShootingTimeline({plan}:{plan:Plan}) {
  const zone=plan.brief.timezone;
  const events=[
    {label:'黄金时刻',at:plan.solar.golden_start,kind:'golden'},
    {label:'日落',at:plan.solar.sunset,kind:'sunset'},
    {label:'蓝调开始',at:plan.solar.blue_start,kind:'blue'},
    {label:'蓝调结束',at:plan.solar.blue_end,kind:'blue'}
  ].filter((event):event is {label:string;at:string;kind:string}=>!!event.at);
  const windows=plan.tasks.map(task=>({id:task.id,label:task.title,start:task.start,end:task.end}));
  if(!events.length&&!windows.length)return null;
  return <section className="shooting-timeline" aria-label="拍摄时间轴">
    <header><Clock3 size={16}/><div><h3>拍摄时间</h3><small>{plan.brief.travel_date} · {zone}</small></div></header>
    {!!events.length&&<div className="light-timeline">{events.map(event=><div className={`light-event ${event.kind}`} key={event.label}><i/><b>{localTime(event.at,zone)}</b><span>{event.label}</span></div>)}</div>}
    {!!windows.length&&<div className="recommended-windows">{windows.map(window=><span key={window.id}><b>{window.label}</b>{localTime(window.start,zone)}–{localTime(window.end,zone)}</span>)}</div>}
  </section>;
}
