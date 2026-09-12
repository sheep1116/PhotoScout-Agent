'use client';
import {Plan,localTime} from '@/lib/types';
import {useState} from 'react';

export default function RecreationResult({plan}:{plan:Plan}) {
  const [missing,setMissing]=useState(false);
  const result=plan.recreation;
  if(!result)return null;
  if(plan.version!==(result.generated_version??1))return <div className="notice">结果已修改，原复刻对照已过期。请重新确认参考机位并生成，以更新拍摄窗口与参数。</div>;
  return <section className="recreation-result"><h3>如何拍出同款</h3>
    <div className="recreation-reference">{!missing?<img src={`/v1/reference-photos/${result.photo_id}/preview`} alt="复刻参考照片" onError={()=>setMissing(true)}/>:<p>参考原图已删除或不可用</p>}<div><b>已选择原机位的复刻建议</b><p>{result.visual.summary}</p><small>{result.location_note}</small></div></div>
    <div className="recreation-windows">{result.windows.map(window=><article key={window.start}><b>拍摄窗口 · {window.date}</b><h4>{localTime(window.start,plan.brief.timezone)}–{localTime(window.end,plan.brief.timezone)}</h4><p>复刻适配度 {window.match} / 100 · 经验评分，不是概率</p><p>朝向：{window.direction_deg==null?'绝对方向未知，现场确认':`${window.direction_deg}°（地标连线，不保证视线）`}</p><p>{window.camera.lens} · 实际 {window.camera.focal_mm} mm / 等效 {window.camera.equivalent_mm} mm</p><p>f/{window.camera.aperture} · {window.camera.shutter_seconds>=1?window.camera.shutter_seconds+' 秒':'1/'+Math.round(1/window.camera.shutter_seconds)+' 秒'} · ISO {window.camera.iso}</p>{window.differences.map((d,j)=><p key={j}>{d}</p>)}<details><summary>器材与试拍调整</summary><p>{window.camera.adjustment}</p>{window.equipment.map((d,j)=><p key={j}>{d}</p>)}</details></article>)}</div>
    <details><summary>复刻难点与注意事项</summary>{result.difficulties.map((d,i)=><p key={i}>{d}</p>)}</details>
  </section>;
}
