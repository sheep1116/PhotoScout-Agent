const pad = (n:number)=>String(n).padStart(2,'0');
export const dateText = (d:Date)=>`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
export const timeText = (d:Date)=>`${pad(d.getHours())}:${pad(d.getMinutes())}`;
export function defaultWindow(now=new Date()) {
  const start=new Date(now);
  start.setSeconds(0,0);
  start.setMinutes((Math.floor(start.getMinutes()/30)+1)*30);
  const end=new Date(start.getTime()+150*60*1000);
  return {travel_date:dateText(start),end_date:dateText(end),start_local:timeText(start),end_local:timeText(end),
    timezone:Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai'};
}
