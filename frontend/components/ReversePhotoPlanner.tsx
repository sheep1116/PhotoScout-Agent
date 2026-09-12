'use client';
import {useRef,useState} from 'react';
import {Camera,Upload,Trash2} from 'lucide-react';
import {api,Brief,Notebook,Plan,Spot} from '@/lib/types';

const term:Record<string,string>={any:'未知',daylight:'日间',sunrise:'日出',golden_hour:'黄金时刻',blue_hour:'蓝调',night:'夜间',clear:'晴朗',overcast:'阴天',rain:'雨天',fog:'雾天',snow:'雪天',unknown:'未知',wide:'广角',normal:'标准焦段',tele:'长焦',high:'高',medium:'中',low:'低'};
type Visual={summary:string;subjects:string[];styles:string[];composition:string;direction:string;light:string;weather:string;season:string;focal_tendency:string;long_exposure:boolean|null;filters:string[];difficulties:string[];hypotheses:{name:string;reason:string;confidence:string}[]};
type Candidate={id:string;name:string;city:string;spot_id:string|null;status:'verified'|'high_inference'|'possible';score:number;camera_instruction:string;reason:string;support:string[];missing:string[];conflicts:string[];verification_scope:string;source_ids:string[];geometry:{first:string;second:string;separation_deg:number;note:string}[]};
type Analysis={id:string;photo_id:string;data_mode:Brief['mode'];candidates:Candidate[];visual:Visual;exif:Record<string,unknown>;spots:Spot[];warnings:string[];sources?:{id:string;title:string;url:string|null}[]};

export default function ReversePhotoPlanner({brief,onPlan}:{brief:Brief;onPlan:(p:Plan)=>void}) {
  const [photo,setPhoto]=useState<{id:string;note:string}|null>(null),[analysis,setAnalysis]=useState<Analysis|null>(null);
  const [region,setRegion]=useState(''),[notes,setNotes]=useState('');
  const [busy,setBusy]=useState(false),[message,setMessage]=useState(''),[error,setError]=useState('');
  const [selected,setSelected]=useState('');
  const file=useRef<HTMLInputElement>(null);
  const confirmed=analysis?.candidates.find(c=>c.id===selected);
  const poll=async(id:string)=>{
    for(let count=0;count<240;count++){
      const job=await api<{status:string;error?:string;events:{message:string}[]}>(`/photo-research/${id}`);
      setMessage(job.events?.at(-1)?.message||'正在分析…');
      if(job.status==='failed')throw new Error(job.error||'请求未完成');
      if(job.status==='complete')return;
      await new Promise(resolve=>setTimeout(resolve,1000));
    }
    throw new Error('等待超时，可稍后从已保存结果查看。');
  };
  const upload=async(image:File)=>{
    if(image.size>10*1024*1024){setError('图片须小于 10 MB');return;}
    setBusy(true);setError('');setAnalysis(null);setSelected('');
    try{
      const response=await fetch('/v1/reference-photos',{method:'POST',headers:{'Content-Type':image.type||'application/octet-stream'},body:image});
      const data=await response.json();if(!response.ok)throw new Error(data.detail||'上传失败');setPhoto(data);
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  };
  const analyze=async()=>{
    if(!photo)return;
    setBusy(true);setError('');setSelected('');setMessage('正在理解参考画面…');
    let identifier='';
    try{
      const result=await api<{research_id:string}>(`/reference-photos/${photo.id}/analysis`,{region_hint:region,notes,data_mode:brief.mode});
      identifier=result.research_id;
      await poll(identifier);
      setAnalysis(await api<Analysis>(`/reference-analyses/${identifier}`));
      setMessage('原机位候选已生成，请核对画面与证据。');
    }catch(e){setError((e as Error).message);if(identifier)try{setAnalysis(await api<Analysis>(`/reference-analyses/${identifier}`));}catch{}}
    finally{setBusy(false);}
  };
  const generate=async()=>{
    if(!analysis||!confirmed?.spot_id)return;
    setBusy(true);setError('');
    try{
      const request={...brief,destination:confirmed.city,location:null,mode:analysis.data_mode,
        reverse_context:{analysis_id:analysis.id,spot_id:confirmed.spot_id}};
      const result=await api<{research_id?:string;notebook?:Notebook}>('/photo-research',request);
      if(!result.research_id){setError(result.notebook?.questions?.join(' ')||'请在下方确认拍摄日期和时间后重试。');return;}
      await poll(result.research_id);onPlan(await api<Plan>(`/plans/${result.research_id}`));setMessage('复刻建议已生成，见下方结果。');
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  };
  const remove=async()=>{
    if(!photo)return;setBusy(true);
    try{const response=await fetch(`/v1/reference-photos/${photo.id}`,{method:'DELETE'});if(!response.ok)throw new Error('删除失败');setPhoto(null);setAnalysis(null);setSelected('');setMessage('参考图及分析已删除');if(file.current)file.current.value='';}
    catch(e){setError((e as Error).message);}finally{setBusy(false);}
  };
  return <section className="reverse-planner" aria-label="参考照片寻找原机位">
    <div className="reverse-controls"><label className="upload-control"><Upload size={18}/>上传参考照片<input ref={file} aria-label="上传参考照片" type="file" accept="image/jpeg,image/png,image/webp" disabled={busy||!!photo} onChange={e=>{if(e.target.files?.[0])void upload(e.target.files[0]);}}/></label>
      <label>地点线索（可选）<input aria-label="参考图搜索区域" value={region} disabled={busy} placeholder="不确定可留空，让 Agent 判断" onChange={e=>{setRegion(e.target.value);setAnalysis(null);setSelected('');}}/></label>
      <label>补充线索（可选）<input aria-label="参考图补充线索" value={notes} maxLength={1500} disabled={busy} placeholder="如地标名称、照片出处" onChange={e=>{setNotes(e.target.value);setAnalysis(null);setSelected('');}}/></label>
    </div>
    <p className="intent-hint">点击分析后，将去元数据预览图发送给模型；原文件不保留。</p>
    {photo&&<div className="reference-preview"><img src={`/v1/reference-photos/${photo.id}/preview`} alt="你上传的参考照片"/><div><button className="primary" disabled={busy} onClick={()=>analyze()}><Camera size={16}/>{busy?'正在处理…':'分析画面并寻找机位'}</button><button className="secondary" disabled={busy} onClick={remove}><Trash2 size={14}/>删除参考图</button><small>JPEG / PNG / WebP · 10 MB 内</small></div></div>}
    {message&&<p role="status">{message}</p>}{error&&<p role="alert" className="error-banner">{error}</p>}
    {analysis?.visual&&<><div className="reference-observations"><b>{analysis.data_mode==='mock'?'离线示例，不是上传图识别':'画面理解 · Agent 视觉推断'}</b><p>{analysis.visual.summary}</p><div className="intent-chips">{[...analysis.visual.subjects,...analysis.visual.styles].map((v,i)=><span className="tag" key={i}>{v}</span>)}</div><p>{analysis.visual.composition}</p><details><summary>推断与文件记录</summary><p>方向：{analysis.visual.direction}</p><p>光线：{term[analysis.visual.light]} · 天气：{term[analysis.visual.weather]} · 焦段倾向：{term[analysis.visual.focal_tendency]}</p><p>季节：{analysis.visual.season}；长曝光：{analysis.visual.long_exposure===null?'未知':analysis.visual.long_exposure?'可能使用':'未见明显线索'}</p><p>EXIF（可能缺失或修改）：{JSON.stringify(analysis.exif)}</p>{analysis.visual.hypotheses.map((h,i)=><p key={i}>地点假设：{h.name} · {h.reason}（{term[h.confidence]}，未核验）</p>)}</details></div>
    <div className="reference-candidates">{analysis.candidates.map(candidate=>{
      const spot=analysis.spots.find(s=>s.id===candidate.spot_id);
      return <article className={`reference-choice ${selected===candidate.id?'selected':''}`} key={candidate.id}>
        <b>{candidate.name}</b><div className="intent-chips"><span className="tag">{{verified:'已核验',high_inference:'高置信推断',possible:'可能机位'}[candidate.status]}</span><small>证据排序分 {candidate.score} / 100</small></div>
        {spot?.photo_references[0]&&<img className="reference-candidate-image" src={`/v1/reference-analyses/${analysis.id}/photos/${spot.photo_references[0].id}`} alt={`${candidate.name} 的地标参考图，非原图机位证明`} onError={e=>{e.currentTarget.style.display='none';}}/>}
        <p>{candidate.camera_instruction||candidate.reason}</p>
        {!!candidate.conflicts.length&&<p className="error-banner">{candidate.conflicts.join('；')}</p>}
        <details><summary>推断依据与待核实信息</summary><p>{candidate.reason}</p><small>{candidate.verification_scope}</small>{[...candidate.support,...candidate.missing].map((text,i)=><p key={i}>{text}</p>)}{candidate.geometry.map((g,i)=><p key={i}>{g.first} / {g.second}：方位间隔 {g.separation_deg}°。{g.note}</p>)}{analysis.sources?.filter(s=>candidate.source_ids.includes(s.id)&&s.url).map(s=><p key={s.id}><a href={s.url!} target="_blank" rel="noreferrer">{s.title}</a></p>)}</details>
        <button className="secondary" disabled={busy} aria-pressed={selected===candidate.id} onClick={()=>setSelected(candidate.id)}>{selected===candidate.id?'已选择原机位':'确认这是原机位'}</button>
      </article>;
    })}</div>
    {!!analysis.warnings.length&&<details><summary>待核实信息</summary>{analysis.warnings.map((w,i)=><p key={i}>{w}</p>)}</details>}
    {!analysis.candidates.length&&<p>暂缺定位线索。请补充可识别地标或照片出处后重试。</p>}
    {confirmed&&<div className="reference-observations"><b>已选择原机位：{confirmed.name}</b><p>如需复刻建议，请在下方确认拍摄日期、时段与器材。</p>{!confirmed.spot_id&&<p>此机位尚未匹配唯一地图坐标，请补充地点线索后重新核验，才能计算天气和光线。</p>}<button className="primary" disabled={!confirmed.spot_id||busy} onClick={generate}>生成该机位的复刻建议</button></div>}</>}
  </section>;
}
