import type {Brief} from './types';

export function defaultWindow(now=new Date(), selectedDate?:string, timezone=Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai') {
  const parts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(now).map(p=>[p.type,p.value]));
  const today=`${parts.year}-${parts.month}-${parts.day}`;
  const date=selectedDate||today;
  return {travel_date:date,end_date:date,start_local:date===today?`${parts.hour}:${parts.minute}`:'00:00',end_local:'23:59',timezone};
}

// Matching a default value does not make an explicit user edit automatic.
export function updateBrief(current:Brief, change:Partial<Brief>, now=new Date()):Brief {
  const next={...current,...change};
  next.auto_time_fields=(current.auto_time_fields||[]).filter(key=>!Object.hasOwn(change,key));
  if(change.travel_date && change.travel_date!==current.travel_date || change.timezone && change.timezone!==current.timezone) {
    const defaults=defaultWindow(now,next.travel_date,next.timezone);
    for(const key of next.auto_time_fields)next[key]=defaults[key];
  }
  return next;
}
