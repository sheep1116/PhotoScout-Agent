'use client';
import {Brief, DestinationLocation, Notebook} from '@/lib/types';
import IntentBuilder from './IntentBuilder';

export default function BriefConfirmation({brief,book,working,onChange,onClose,onResolve,onApprove,onSelect}:{brief:Brief;book:Notebook;working:boolean;onChange:(v:Partial<Brief>)=>void;onClose:()=>void;onResolve:()=>unknown;onApprove:()=>unknown;onSelect:(location:DestinationLocation)=>void}) {
  return <div className="overlay" onClick={onClose}><section className="modal brief-confirmation" role="dialog" aria-modal="true" aria-labelledby="confirm-title" onClick={e=>e.stopPropagation()}>
    <button className="close" aria-label="关闭确认" onClick={onClose}>×</button>
    <div className="eyebrow muted">YOUR PHOTOGRAPHY BRIEF</div><h2 id="confirm-title">让我们对齐这次出发。</h2>
    <p>{book.parser==='model'?'模型已解析你的描述':'已整理明确词句与默认值'}；以下条件都可以修改。</p>
    <div className="recognized">已从描述中识别：{book.recognized.join(' / ')||'未识别到明确标签，沿用默认建议'}</div>
    <blockquote>{brief.text||'未填写描述，使用下面的条件发现机位。'}</blockquote>
    <label>目的地<input aria-label="确认目的地" value={brief.destination} onChange={e=>onChange({destination:e.target.value})}/></label>
    <button className="secondary" disabled={working} onClick={()=>onResolve()}>查询 / 重新确认地点</button>
    {brief.location&&<div className="notice">已选：{brief.location.city} {brief.location.name}<small>高德地点 · {brief.location.address}</small></div>}
    {!!book.location_choices.length&&<fieldset className="location-choices"><legend>这个名称有多个地点，请选择</legend>{book.location_choices.map(location=><button className="history-row" key={location.id} onClick={()=>onSelect(location)}><span>{location.city} {location.name}<small>{location.address} · {location.poi_id?'景点/地标':'行政区域'}</small></span></button>)}</fieldset>}
    {!!book.questions.length&&<p role="alert">{book.questions.join(' ')}</p>}
    <div className="field-row"><label>拍摄日期<input type="date" aria-label="确认拍摄日期" value={brief.travel_date} onChange={e=>onChange({travel_date:e.target.value})}/></label><label>结束日期<input type="date" aria-label="确认结束日期" value={brief.end_date||brief.travel_date} onChange={e=>onChange({end_date:e.target.value})}/></label></div>
    <div className="field-row"><label>开始时间<input type="time" aria-label="确认开始时间" value={brief.start_local} onChange={e=>onChange({start_local:e.target.value})}/></label><label>结束时间<input type="time" aria-label="确认结束时间" value={brief.end_local} onChange={e=>onChange({end_local:e.target.value})}/></label></div>
    <p className="intent-hint">时间按 {brief.timezone}；多个摄影方向同等参与。灰色默认建议并非限制。</p>
    <IntentBuilder brief={brief} onChange={onChange}/>
    {!!brief.intent.other_requirements?.length&&<label>其他摄影需求<textarea aria-label="其他摄影需求" value={brief.intent.other_requirements.join('；')} onChange={e=>onChange({intent:{...brief.intent,other_requirements:e.target.value.split('；')}})}/></label>}
    <p>器材：{brief.lenses.map(l=>l.name).join(' / ')||'未指定镜头，提供通用起点'} · {brief.tripod?'有三脚架':'手持'}</p>
    <div className="notice">{book.assumptions.map((a,i)=><p key={i}>{a}</p>)}<p>{brief.mode==='live'?'确认后联网搜索，使用已配置账户，可能产生费用。':'离线示例，不代表实际天气和现场。'}</p></div>
    <button className="primary" disabled={working||!brief.destination||!brief.travel_date||!brief.start_local||!brief.end_local||book.location_status==='needs_choice'&&!brief.location} onClick={()=>onApprove()}>{working?'正在核对…':'确认需求，开始侦察'}</button>
  </section></div>;
}
