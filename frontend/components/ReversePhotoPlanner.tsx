'use client';
import {useRef,useState} from 'react';
import {Camera,Upload,Trash2} from 'lucide-react';
import {api,Brief,DestinationLocation,Notebook,Plan,Spot} from '@/lib/types';

const term:Record<string,string>={any:'未知',daylight:'日间',sunrise:'日出',golden_hour:'黄金时刻',blue_hour:'蓝调',night:'夜间',clear:'晴朗',overcast:'阴天',rain:'雨天',fog:'雾天',snow:'雪天',unknown:'未知',wide:'广角',normal:'标准焦段',tele:'长焦',high:'高',medium:'中',low:'低'};
type Visual={summary:string;subjects:string[];styles:string[];composition:string;direction:string;light:string;weather:string;season:string;focal_tendency:string;long_exposure:boolean|null;filters:string[];difficulties:string[];hypotheses:{name:string;reason:string;confidence:string}[]};
type Analysis={id:string;photo_id:string;mode:string;brief:Brief;visual:Visual;exif:Record<string,unknown>;spots:Spot[];warnings:string[];sources?:{id:string;title:string;url:string|null}[];gps_distances?:Record<string,number>};

export default function ReversePhotoPlanner({brief,onPlan}:{brief:Brief;onPlan:(p:Plan)=>void}) {
  const [photo,setPhoto]=useState<{id:string;note:string}|null>(null),[analysis,setAnalysis]=useState<Analysis|null>(null);
  const [region,setRegion]=useState<string|null>(null),[mode,setMode]=useState('original'),[days,setDays]=useState(7);
  const [busy,setBusy]=useState(false),[message,setMessage]=useState(''),[error,setError]=useState('');
  const [choices,setChoices]=useState<DestinationLocation[]>([]),[selected,setSelected]=useState('');
  const file=useRef<HTMLInputElement>(null);
  const [clarified,setClarified]=useState<Brief|null>(null);
  const area=region??brief.destination;
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
  const analyze=async(location?:DestinationLocation)=>{
    if(!photo)return;
    setBusy(true);setError('');setSelected('');setMessage('正在理解参考画面…');
    let identifier='';
    try{
      const request={...brief,destination:area,text:brief.text,location:location||null,reverse_context:undefined};
      const result=await api<{research_id?:string;notebook?:Notebook}>(`/reference-photos/${photo.id}/analysis`,{brief:request,mode});
      if(result.notebook){setChoices(result.notebook.location_choices);setClarified(result.notebook.brief);setMessage('请选择地点，或补充城市后重试。');return;}
      identifier=result.research_id!;setChoices([]);
      await poll(identifier);
      setAnalysis(await api<Analysis>(`/reference-analyses/${identifier}`));
      setMessage('请选择一个候选，再比较未来拍摄条件。');
    }catch(e){setError((e as Error).message);if(identifier)try{setAnalysis(await api<Analysis>(`/reference-analyses/${identifier}`));}catch{}}
    finally{setBusy(false);}
  };
  const generate=async()=>{
    if(!analysis||!selected)return;
    setBusy(true);setError('');
    try{
      // Keep confirmed destination and data mode, but use the user's current date and equipment.
      const request={...brief,destination:analysis.brief.destination,location:analysis.brief.location,mode:analysis.brief.mode,
        reverse_context:{analysis_id:analysis.id,spot_id:selected,days}};
      const result=await api<{research_id?:string;notebook?:Notebook}>('/photo-research',request);
      if(!result.research_id){setError('地点确认已过期，请重新分析并确认候选。');return;}
      await poll(result.research_id);onPlan(await api<Plan>(`/plans/${result.research_id}`));setMessage('复刻建议已生成，见下方结果。');
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  };
  const remove=async()=>{
    if(!photo)return;setBusy(true);
    try{const response=await fetch(`/v1/reference-photos/${photo.id}`,{method:'DELETE'});if(!response.ok)throw new Error('删除失败');setPhoto(null);setAnalysis(null);setSelected('');setMessage('参考图及分析已删除');if(file.current)file.current.value='';}
    catch(e){setError((e as Error).message);}finally{setBusy(false);}
  };
  return <section className="reverse-planner" aria-label="参考照片复刻">
    <div className="reverse-controls"><label className="upload-control"><Upload size={18}/>上传参考照片<input ref={file} aria-label="上传参考照片" type="file" accept="image/jpeg,image/png,image/webp" disabled={busy||!!photo} onChange={e=>{if(e.target.files?.[0])void upload(e.target.files[0]);}}/></label>
      <label>复刻目标<select aria-label="复刻目标" value={mode} disabled={busy} onChange={e=>{setMode(e.target.value);setAnalysis(null);}}><option value="original">寻找原机位</option><option value="similar">在这里拍同款</option></select></label>
      <label>城市 / 搜索区域<input aria-label="参考图搜索区域" value={area} disabled={busy} placeholder="不确定时可先留空分析图片" onChange={e=>{setRegion(e.target.value);setAnalysis(null);setChoices([]);}}/></label>
      <label>比较未来天数<select aria-label="比较未来天数" value={days} onChange={e=>setDays(Number(e.target.value))}>{[1,3,7].map(n=><option key={n} value={n}>{n} 天</option>)}</select></label>
    </div>
    <p className="intent-hint">日期、时段与器材沿用下方设置。仅在点击分析后发送去元数据预览图到模型服务；原文件不保留。</p>
    {photo&&<div className="reference-preview"><img src={`/v1/reference-photos/${photo.id}/preview`} alt="你上传的参考照片"/><div><button className="primary" disabled={busy} onClick={()=>analyze()}><Camera size={16}/>{busy?'正在处理…':'分析画面并寻找机位'}</button><button className="secondary" disabled={busy} onClick={remove}><Trash2 size={14}/>删除参考图</button><small>JPEG / PNG / WebP · 10 MB 内</small></div></div>}
    {!!choices.length&&<div className="location-choices">{choices.map(c=><button className="history-row" key={c.id} disabled={busy} onClick={()=>{if(clarified)setRegion(clarified.destination);void analyze(c);}}>{c.city} {c.name}</button>)}</div>}
    {message&&<p role="status">{message}</p>}{error&&<p role="alert" className="error-banner">{error}</p>}
    {analysis?.visual&&<><div className="reference-observations"><b>{analysis.brief.mode==='mock'?'离线示例，不是上传图识别':'画面理解 · Agent 视觉推断'}</b><p>{analysis.visual.summary}</p><div className="intent-chips">{[...analysis.visual.subjects,...analysis.visual.styles].map((v,i)=><span className="tag" key={i}>{v}</span>)}</div><p>{analysis.visual.composition}</p><details><summary>推断与文件记录</summary><p>方向：{analysis.visual.direction}</p><p>光线：{term[analysis.visual.light]} · 天气：{term[analysis.visual.weather]} · 焦段倾向：{term[analysis.visual.focal_tendency]}</p><p>季节：{analysis.visual.season}；长曝光：{analysis.visual.long_exposure===null?'未知':analysis.visual.long_exposure?'可能使用':'未见明显线索'}</p><p>EXIF（可能缺失或修改）：{JSON.stringify(analysis.exif)}</p>{analysis.visual.hypotheses.map((h,i)=><p key={i}>地点假设：{h.name} · {h.reason}（{term[h.confidence]}，未核验）<button className="secondary" disabled={busy} onClick={()=>{setRegion(h.name);setAnalysis(null);}}>采用此地点线索</button></p>)}</details></div>
    <div className="reference-candidates">{analysis.spots.map(spot=><button className={`reference-choice ${selected===spot.id?'selected':''}`} key={spot.id} disabled={busy} aria-pressed={selected===spot.id} onClick={()=>setSelected(spot.id)}><b>{spot.name}</b>{spot.photo_references[0]&&<img className="reference-candidate-image" src={`/v1/reference-analyses/${analysis.id}/photos/${spot.photo_references[0].id}`} alt={`${spot.name} 的来源参考图`} onError={e=>{e.currentTarget.style.display='none';}}/>}<p>{spot.camera_instruction}</p><small>{spot.viewpoint_status==='mapped_viewpoint'?'地标已匹配':'区域级候选'} · {mode==='similar'?'相似效果候选':'原机位身份未确认'}</small>{analysis.gps_distances?.[spot.id]!=null&&<p>距 EXIF GPS 直线约 {analysis.gps_distances[spot.id]} km（文件记录待核实）</p>}</button>)}</div>
    {!!analysis.warnings.length&&<details><summary>来源与待核实信息</summary>{analysis.sources?.filter(s=>s.url).map(s=><p key={s.id}><a href={s.url!} target="_blank" rel="noreferrer">{s.title}</a></p>)}{analysis.warnings.map((w,i)=><p key={i}>{w}</p>)}</details>}
    {!analysis.spots.length&&<p>未找到可核验机位。请补充上方城市或改为相似效果后重试。</p>}
    <button className="primary" disabled={!selected||busy} onClick={generate}>确认候选，生成同款拍摄建议</button></>}
  </section>;
}
