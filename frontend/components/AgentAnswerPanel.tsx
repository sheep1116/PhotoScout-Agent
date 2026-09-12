'use client';
import {ExternalLink, MapPin, Sparkles} from 'lucide-react';
import type {Plan} from '@/lib/types';

const status:Record<string,string>={
  mapped:'地图与来源已关联',area:'仅定位到所属区域',map_only:'地图可定位 · 来源待核验',
  unlocated:'站位待定位',rejected:'超出已确认范围'
};

export default function AgentAnswerPanel({plan,onSelect}:{plan:Plan;onSelect:(id:string)=>void}) {
  const answer=plan.agent_answer;
  if(!answer || (!answer.summaries.length&&!answer.candidates.length)) return null;
  return <section className="agent-answer" aria-label="联网 Agent 原始建议">
    <header><div><span className="eyebrow muted">AGENT FIRST</span><h3><Sparkles size={17}/>千问给出的拍摄建议</h3></div><span className="agent-disclaimer">原始建议已保留 · 核验结果见每条状态</span></header>
    <div className="agent-summaries">{answer.summaries.map((summary,i)=><p key={i}>{summary}</p>)}</div>
    {!!answer.candidates.length&&<div className="agent-candidates">{answer.candidates.map(candidate=>{
      const sources=plan.sources.filter(source=>candidate.source_ids.includes(source.id));
      return <article key={candidate.id} className={`agent-candidate ${candidate.verification_status}`}>
        <div className="agent-candidate-title"><div><h4>{candidate.name}</h4><small>{candidate.place_name||candidate.camera_poi||'地点待确认'}</small></div><span className="tag">{status[candidate.verification_status]||candidate.verification_status}</span></div>
        {candidate.camera_instruction&&<p><b>怎么站：</b>{candidate.camera_instruction}</p>}
        {candidate.shooting_direction&&<p><b>朝向：</b>{candidate.shooting_direction}</p>}
        {candidate.composition&&<p><b>构图：</b>{candidate.composition}</p>}
        {candidate.recommended_time&&<p><b>推荐时间：</b>{candidate.recommended_time}</p>}
        {candidate.time_judgment&&<p><b>指定时段：</b>{candidate.time_judgment}</p>}
        {candidate.equipment_advice&&<p><b>器材：</b>{candidate.equipment_advice}</p>}
        {Object.keys(candidate.settings_advice).length>0&&<div className="agent-settings">{Object.entries(candidate.settings_advice).map(([key,value])=><span key={key}><small>{key}</small>{value}</span>)}</div>}
        <div className="agent-verification"><b>PhotoScout 核验：</b>{candidate.verification_note}</div>
        <footer>{candidate.mapped_spot_id&&plan.spots.some(spot=>spot.id===candidate.mapped_spot_id)&&<button onClick={()=>onSelect(candidate.mapped_spot_id!)}><MapPin size={12}/>在地图查看</button>}{sources.map(source=>source.url&&<a key={source.id} href={source.url} target="_blank" rel="noreferrer">{source.title}<ExternalLink size={11}/></a>)}</footer>
      </article>;
    })}</div>}
  </section>;
}
