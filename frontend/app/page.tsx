'use client';
import {useEffect, useRef, useState} from 'react';
import {Aperture, ArrowDownToLine, ArrowRight, ArrowUpRight, BookOpen, Camera, Check, ChevronDown, Clock3, CloudSun, Compass, ExternalLink, Footprints, History, Info, LoaderCircle, MapPin, Menu, Moon, Plus, RotateCcw, ShieldCheck, SlidersHorizontal, Sparkles, Sun, Users, X} from 'lucide-react';
import IntentBuilder, {categoryLabels} from '@/components/IntentBuilder';
import BriefConfirmation from '@/components/BriefConfirmation';
import PhotoGallery from '@/components/PhotoGallery';
import {defaultWindow, deriveEndDate, updateBrief} from '@/lib/defaults';
import FieldHint from '@/components/FieldHint';
import ReversePhotoPlanner from '@/components/ReversePhotoPlanner';
import RecreationResult from '@/components/RecreationResult';
import ScoutMap from '@/components/ScoutMap';
import ShootingTimeline from '@/components/ShootingTimeline';
import {api, AgentCandidate, Brief, Notebook, Evidence, localTime, Plan, Proposal, Task} from '@/lib/types';

const demo: Brief = {text:'南京紫金山，想拍一组自然、电影感的人像，不想走太远。',destination:'南京紫金山',travel_date:'2026-10-03',start_local:'14:00',end_local:'19:00',timezone:'Asia/Shanghai',intent:{categories:['portrait'],recommendation_mode:'multiple',subjects:[],styles:[],light:'golden_hour',preferences:{}},lenses:[{name:'35mm F1.8',min_mm:35,max_mm:35,max_aperture:1.8},{name:'85mm F1.8',min_mm:85,max_mm:85,max_aperture:1.8}],sensor:'full_frame',tripod:false,mode:'mock'};
const initial:Brief = {...demo,text:'',destination:'',travel_date:'',start_local:'',end_local:'',intent:{categories:[],recommendation_mode:'best',subjects:[],styles:[],light:'any',preferences:{}},lenses:[],mode:'live'};
const labels:Record<string,string> = {FIXTURE:'演示数据',UNKNOWN:'未知',REPORTED:'来源报告',INFERRED:'规则推断',CALCULATED:'工具计算',VERIFIED:'已核验',STALE:'已过期',CONFLICT:'来源冲突',USER_CONFIRMED:'用户记录'};
const kinds:Record<string,string> = {official:'官方',community:'社区',media:'媒体',search:'搜索线索',fixture:'离线示例',tool:'确定性工具',user:'用户记录'};

export default function Home() {
  const [brief,setBrief] = useState<Brief>(initial), [plan,setPlan] = useState<Plan|null>(null);
  const [busy,setBusy] = useState(false), [events,setEvents] = useState<{stage:string;message:string}[]>([]);
  const [error,setError] = useState(''), [tab,setTab] = useState('spots'), [selected,setSelected] = useState('');
  const [confirm,setConfirm] = useState(false), [reviewBook,setReviewBook] = useState<Notebook|null>(null);
  const [drawer,setDrawer] = useState<Evidence[]|null>(null), [proposal,setProposal] = useState<Proposal|null>(null);
  const [history,setHistory] = useState<{id:string;destination:string;date:string;categories:string[];version:number}[]>([]);
  const [showHistory,setShowHistory] = useState(false), [working,setWorking] = useState(false), [mobileNav,setMobileNav] = useState(false);
  const [health,setHealth] = useState<{dashscope_configured:boolean;amap_configured:boolean}|null>(null);
  const [positionEdit,setPositionEdit] = useState<{spot_id:string;name:string;lat:number;lon:number;role:string}|null>(null);
  const [notice,setNotice] = useState('');
  const stream = useRef<EventSource|null>(null);
  const resultRef = useRef<HTMLElement>(null);
  const destinationEdited = useRef(false);
  const [locationNote,setLocationNote] = useState('正在建议当前位置…');
  useEffect(()=>{
    let alive=true;
    setBrief(b=>({...b,...defaultWindow(),auto_time_fields:['start_local','end_local']}));
    api<typeof health>('/health').then(setHealth).catch(()=>{});
    const applyLocation = (result:{city:string|null;note:string},origin?:{origin_lat:number;origin_lon:number})=>{
      if(!alive || destinationEdited.current)return;
      setLocationNote(result.note);
      if(result.city)setBrief(b=>({...b,destination:result.city!,...origin}));
    };
    const fallback=()=>{if(alive&&!destinationEdited.current)api<{city:string|null;note:string}>('/location/ip').then(r=>applyLocation(r)).catch(()=>setLocationNote('定位不可用，请手动填写目的地。'));};
    if(navigator.geolocation)navigator.geolocation.getCurrentPosition(async position=>{
      if(!alive||destinationEdited.current)return;
      const origin={origin_lat:Number(position.coords.latitude.toFixed(3)),origin_lon:Number(position.coords.longitude.toFixed(3))};
      try{const result=await api<{city:string|null;note:string}>('/location/reverse',{lat:origin.origin_lat,lon:origin.origin_lon});if(result.city)applyLocation(result,origin);else fallback();}catch{fallback();}
    },fallback,{timeout:6000,maximumAge:300000,enableHighAccuracy:false});else fallback();
    return ()=>{alive=false;stream.current?.close();};
  },[]);
  const patch = (value: Partial<Brief>)=>{
    if(Object.hasOwn(value,'text'))setReviewBook(null);
    if(Object.hasOwn(value,'destination')){setReviewBook(b=>b?{...b,location_choices:[],location_status:'unresolved'}:b);destinationEdited.current=true;setLocationNote('使用你填写的目的地。');}
    setBrief(b=>({...updateBrief(b,value),...(Object.hasOwn(value,'destination')?{location:null}:{}),edited_fields:value.edited_fields||[...new Set([...(b.edited_fields||[]),...Object.keys(value).filter(k=>!['text','intent','location'].includes(k))])]}));
  };
  const seed = (genre:'portrait'|'cityscape')=>{setError('');destinationEdited.current=true;setLocationNote('已选择演示模板');setBrief({...demo,end_date:demo.travel_date,edited_fields:[],intent:{categories:[genre],recommendation_mode:'multiple',subjects:[],styles:[],light:genre==='cityscape'?'blue_hour':'golden_hour',preferences:{}},
    ...(genre==='cityscape'?{text:'南京拍城市夜景，想拍古城与现代天际线同框。',destination:'南京',start_local:'16:30',end_local:'21:00',tripod:true,
      lenses:[{name:'16–35mm F2.8',min_mm:16,max_mm:35,max_aperture:2.8},{name:'70–200mm F4',min_mm:70,max_mm:200,max_aperture:4}]}:{})});};
  const payload = (b:Brief)=>({...b,travel_date:b.travel_date||null,end_date:deriveEndDate(b.travel_date,b.start_local,b.end_local),start_local:b.start_local||null,end_local:b.end_local||null});
  const review = async()=>{setError('');setWorking(true);try{const book=await api<Notebook>('/notebook',payload(brief));if(book.missing_fields.length){setError(book.questions.join(' '));return;}destinationEdited.current=true;setBrief(book.brief);setReviewBook(book);setConfirm(true);}catch(e){setError((e as Error).message);}finally{setWorking(false);}};
  const resolveLocation = async()=>{setWorking(true);try{const book=await api<Notebook>('/destinations/resolve',payload(brief));setBrief(book.brief);setReviewBook(old=>({...book,recognized:old?.recognized||[],parser:old?.parser||'defaults',parsed_fields:old?.parsed_fields||[],assumptions:old?.assumptions||book.assumptions}));return book;}catch(e){setError((e as Error).message);}finally{setWorking(false);}};
  const approveBrief = async()=>{const book=await resolveLocation();if(book&&!book.missing_fields.length&&!['needs_choice','unavailable'].includes(book.location_status))await generate(book.brief);};
  const generate = async(confirmed:Brief=brief)=>{setConfirm(false);setError('');setBusy(true);setEvents([]);setProposal(null);
    try{const job=await api<{research_id:string;status:string}>('/photo-research',confirmed,{'Idempotency-Key':crypto.randomUUID()});
      if(!job.research_id)throw new Error('需求还不完整，请重新确认。');
      const es=new EventSource(`/v1/photo-research/${job.research_id}/events`);stream.current=es;
      es.onmessage=e=>{setEvents(v=>[...v,JSON.parse(e.data)]);};
      es.addEventListener('done',async e=>{es.close();try{const status=JSON.parse((e as MessageEvent).data);if(status.status==='failed')throw new Error(status.error);const p=await api<Plan>(`/plans/${job.research_id}`);setPlan(p);setSelected(p.tasks[0]?.spot_id||'');setTab('spots');setTimeout(()=>resultRef.current?.scrollIntoView({behavior:'smooth',block:'start'}),80);}catch(err){setError((err as Error).message);}finally{setBusy(false);}});
      es.onerror=()=>{es.close();setBusy(false);setError('进度连接中断。任务可能仍在运行，可稍后从「我的发现」打开。');};
    }catch(e){setBusy(false);setError((e as Error).message);}
  };
  const cite = (ids:string[])=>{if(plan)setDrawer(plan.evidence.filter(e=>ids.includes(e.id)));};
  const change = async(task:Task,reason:string)=>{if(!plan)return;setWorking(true);setError('');try{setProposal(await api<Proposal>(`/plans/${plan.id}/proposals`,{task_id:task.id,reason,version:plan.version}));}catch(e){setError((e as Error).message);}finally{setWorking(false);}};
  const decide = async(approve:boolean)=>{if(!proposal)return;setWorking(true);try{setPlan(await api<Plan>(`/proposals/${proposal.id}/decision`,{approve,version:proposal.base_version}));setProposal(null);}catch(e){setError((e as Error).message);}finally{setWorking(false);}};
  const undo = async()=>{if(!plan)return;setWorking(true);try{setPlan(await api<Plan>(`/plans/${plan.id}/undo`,{version:plan.version}));setProposal(null);}catch(e){setError((e as Error).message);}finally{setWorking(false);}};
  const refresh = async()=>{if(!plan)return;setWorking(true);setNotice('');try{const result=await api<{proposal:Proposal|null;message:string}>(`/plans/${plan.id}/refresh`,{version:plan.version});setProposal(result.proposal);setNotice(result.message);}catch(e){setError((e as Error).message);}finally{setWorking(false);}};
  const confirmPosition = async()=>{if(!plan||!positionEdit)return;setWorking(true);try{setProposal(await api<Proposal>(`/plans/${plan.id}/spots/${positionEdit.spot_id}/confirm`,{lat:positionEdit.lat,lon:positionEdit.lon,role:positionEdit.role,version:plan.version}));setPositionEdit(null);}catch(e){setError((e as Error).message);}finally{setWorking(false);}};
  const loadHistory = async()=>{setShowHistory(true);try{setHistory(await api<typeof history>('/plans'));}catch(e){setError((e as Error).message);}};
  const exportPlan = ()=>{if(!plan)return;const url=URL.createObjectURL(new Blob([JSON.stringify(plan,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`PhotoScout-${plan.brief.travel_date}-v${plan.version}.json`;a.click();URL.revokeObjectURL(url);};
  const time = (v:string|null)=>localTime(v,plan?.brief.timezone);

  const active=plan?.tasks.filter(t=>t.status!=='CANCELLED')||[];
  const structuredCandidates=plan?.agent_answer?.candidates||[];
  const candidateBySpot=new Map<string,AgentCandidate>();
  [...structuredCandidates].sort((a,b)=>(a.rank||99)-(b.rank||99)).forEach(candidate=>{
    if(candidate.mapped_spot_id&&!candidateBySpot.has(candidate.mapped_spot_id))candidateBySpot.set(candidate.mapped_spot_id,candidate);
  });
  const pendingCandidates=structuredCandidates.filter(candidate=>!candidate.mapped_spot_id||!plan?.tasks.some(task=>task.spot_id===candidate.mapped_spot_id));
  const cardTasks=Array.from(new Map((plan?.tasks||[]).map(task=>[task.spot_id,task])).values()).sort((a,b)=>(candidateBySpot.get(a.spot_id)?.rank||99)-(candidateBySpot.get(b.spot_id)?.rank||99));

  return <div className="shell">
    <aside className={`sidebar ${mobileNav?'mobile-open':''}`}>
      <a className="brand" href="/" aria-label="PhotoScout 首页"><span className="brand-icon"><Aperture size={23}/></span><span>PhotoScout<span className="brand-dot">.</span></span></a>
      <div className="workspace-label">你的摄影工作台 <span>BETA</span></div>
      <nav aria-label="主导航"><button className={!showHistory?'nav-item active':'nav-item'} onClick={()=>{setShowHistory(false);setMobileNav(false);}}><Compass size={19}/>机位发现<span className="nav-indicator"/></button><button className={showHistory?'nav-item active':'nav-item'} onClick={loadHistory}><BookOpen size={19}/>我的发现</button><button className="nav-item" onClick={()=>{setTab('sources');resultRef.current?.scrollIntoView({behavior:'smooth'});}}><ShieldCheck size={19}/>证据与来源</button></nav>
      <div className="sidebar-section">灵感，从这里开始 <span>↙</span></div>
      <button className="seed-item" onClick={()=>seed('portrait')}><div className="seed-art portrait-art"><Sun size={18}/></div><span>紫金山的光与影<small>南京 · 旅行人像</small></span><ArrowUpRight size={14}/></button>
      <button className="seed-item" onClick={()=>seed('cityscape')}><div className="seed-art night-art"><Moon size={18}/></div><span>蓝调时刻的南京<small>南京 · 城市夜景</small></span><ArrowUpRight size={14}/></button>
      <div className="sidebar-bottom"><div className="trust-note"><ShieldCheck size={18}/><b>每一条建议，都有来处</b><p>真实来源、明确的不确定性，<br/>让灵感安心落地。</p></div><div className="local-status"><span className="status-dot"/><span>本地工作空间<small>密钥仅保存在服务端</small></span><span className="avatar">P</span></div></div>
    </aside>

    <main className="main">
      <header className="topbar"><div><button className="mobile-menu icon-btn" aria-label="打开导航" onClick={()=>setMobileNav(!mobileNav)}><Menu size={20}/></button><span className="breadcrumb">工作台</span><span className="slash">/</span><b>机位发现</b></div><div className="topbar-right"><span className="local-pill"><i/> LOCAL FIRST</span><button className="icon-btn" title="查看已保存计划" onClick={loadHistory}><History size={18}/></button></div></header>
      <div className="page-content">
        <section className="intro"><div><div className="eyebrow"><span/> YOUR NEXT FRAME STARTS HERE</div><h1>去光发生的地方<span>。</span></h1><p>把一个拍摄想法，变成有据可循的机位选择。</p></div><div className="intro-mark"><Aperture size={74} strokeWidth={.8}/><span>EXPLORE / FRAME / CREATE</span></div></section>

        {error&&events.some(e=>e.stage==='warning')&&<details className="notice"><summary>查看本次发现未完成的原因</summary>{events.filter(e=>e.stage==='warning').map((e,i)=><p key={i}>{e.message}</p>)}</details>}
        {error&&<div role="alert" className="error-banner"><Info size={18}/><span>{error}</span><button aria-label="关闭错误" onClick={()=>setError('')}><X size={17}/></button></div>}
        {notice&&<div role="status" className="notice">{notice}</div>}

        <details className="reference-entry"><summary><Camera size={18}/>参考照片寻找原机位 <small>上传照片，推断并核验拍摄位置</small></summary><ReversePhotoPlanner brief={brief} onPlan={p=>{setPlan(p);setSelected(p.tasks[0]?.spot_id||'');setTab('spots');setTimeout(()=>resultRef.current?.scrollIntoView({behavior:'smooth'}),80);}}/></details><div className="workbench">
          <section className="brief-panel">
            <div className="panel-title"><span><SlidersHorizontal size={17}/>这次，想拍什么？</span><span className="step-label">01 / BRIEF</span></div>
            <div className="field-heading"><label className="input-label" htmlFor="intent">说说你的拍摄想法</label><FieldHint label="拍摄描述说明">灰色为自动建议，手动修改优先。</FieldHint></div>
            <div className="intent-box"><textarea id="intent" value={brief.text} onChange={e=>patch({text:e.target.value})} placeholder="明天想在南京拍电影感的湖面倒影，不想走太远。"/><Sparkles size={17}/></div>

            <div className="field-row"><label><span className="field-heading">目的地<FieldHint label="城市定位说明">{locationNote.startsWith('使用')?'使用你填写的地点。':locationNote.includes('不可用')?'定位不可用，请填写目的地。':'城市由网络或设备定位建议，请核对。'}</FieldHint></span><div className="icon-input destination-input">{brief.destination&&!destinationEdited.current&&<span className="auto-location">自动定位</span>}<MapPin size={15}/><input aria-label="目的地" className={(brief.edited_fields?.includes("destination")||reviewBook?.parsed_fields.includes("destination"))?"":"suggested-default"} value={brief.destination} onChange={e=>patch({destination:e.target.value})}/></div></label><label><span className="field-heading">拍摄日期</span><input aria-label="拍摄日期" className={(brief.edited_fields?.includes("travel_date")||reviewBook?.parsed_fields.includes("travel_date"))?"":"suggested-default"} type="date" value={brief.travel_date} onChange={e=>patch({travel_date:e.target.value})}/></label></div>
            <div className="field-row"><label><span className="field-heading">开始时间<FieldHint label="拍摄时间说明">按 {brief.timezone} 当地时间；结束时间早于开始时间时自动按跨午夜、次日结束计算。</FieldHint>{brief.auto_time_fields?.includes('start_local')&&<span className="auto-badge">自动</span>}</span><input type="time" aria-label="开始时间" className={brief.auto_time_fields?.includes("start_local")?"suggested-default":""} value={brief.start_local} onChange={e=>patch({start_local:e.target.value})}/></label><label><span className="field-heading">结束时间{brief.auto_time_fields?.includes('end_local')&&<span className="auto-badge">自动</span>}</span><input type="time" aria-label="结束时间" className={brief.auto_time_fields?.includes("end_local")?"suggested-default":""} value={brief.end_local} onChange={e=>patch({end_local:e.target.value})}/></label></div>

            <IntentBuilder brief={brief} onChange={patch}/>
            <details className="gear-details"><summary><span><Camera size={16}/>摄影器材</span><ChevronDown size={15}/></summary><div className="gear-content">
              <label>画幅<select aria-label="画幅" value={brief.sensor} onChange={e=>patch({sensor:e.target.value})}><option value="full_frame">全画幅</option><option value="aps_c">APS-C（1.5×）</option><option value="m43">M4/3（2×）</option><option value="phone">手机（等效焦段）</option></select></label>
              <div className="lens-header"><span>镜头 · 实际焦段 / 最大光圈</span><button title="添加镜头" onClick={()=>patch({lenses:[...brief.lenses,{name:'新镜头',min_mm:24,max_mm:70,max_aperture:4}].slice(0,8)})}><Plus size={15}/></button></div>
              {brief.lenses.map((lens,i)=><div className="lens-row" key={i}><input aria-label={`镜头${i+1}名称`} value={lens.name} onChange={e=>patch({lenses:brief.lenses.map((l,j)=>j===i?{...l,name:e.target.value}:l)})}/>{(['min_mm','max_mm','max_aperture'] as const).map(k=><input key={k} type="number" step="0.1" min="0.7" aria-label={`镜头${i+1}${k}`} value={lens[k]} onChange={e=>patch({lenses:brief.lenses.map((l,j)=>j===i?{...l,[k]:Number(e.target.value)}:l)})}/>)}<button title="移除镜头" onClick={()=>patch({lenses:brief.lenses.filter((_,j)=>j!==i)})}><X size={13}/></button></div>)}
              <label><input type="checkbox" checked={brief.tripod} onChange={e=>patch({tripod:e.target.checked})}/>携带三脚架</label>
            </div></details>
            {brief.lenses.length>0&&<div className="brief-summary"><span>{brief.lenses.map(l=>l.name).join(' · ')}</span></div>}
            <div className="mode-row"><label><select aria-label="数据模式" value={brief.mode} onChange={e=>patch({mode:e.target.value as Brief['mode']})}><option value="mock">离线演示</option><option value="live">Live · 联网发现</option></select></label><span>{brief.mode==='mock'?'无需网络与 API':'将调用已配置的 API'}</span></div>
            <button className="primary generate" disabled={busy||working} onClick={review}>{busy?<LoaderCircle size={18} className="spin"/>:<Sparkles size={18}/>} {busy?'正在为你侦察…':'发现值得拍的机位'}<ArrowRight size={17}/></button>

            {!!reviewBook?.recognized.length&&<div className="recognized">已从描述中识别：{reviewBook.recognized.join(' / ')}</div>}
          </section>

          <div className="map-column"><ScoutMap plan={plan} selected={selected} onSelect={setSelected}/>
            {plan&&selected&&<div className="map-edit-row"><span>选中：{plan.spots.find(s=>s.id===selected)?.name}</span><button onClick={()=>{const s=plan.spots.find(s=>s.id===selected);if(s)setPositionEdit({spot_id:s.id,name:s.name,lat:s.camera.lat,lon:s.camera.lon,role:'camera'});}}>记录站位 / 入口 ↗</button></div>}
            <div className="insight-row"><div className="insight"><div className="insight-icon"><Sun size={20}/></div><div><span>黄金光线</span><strong>{plan?time(plan.solar.golden_start):'随日期计算'}<small>{plan?'当地时间 · Astral':'日落前的温柔时刻'}</small></strong></div>{plan&&<button className="tiny-link" onClick={()=>cite(plan.solar.evidence_ids)}>依据 ↗</button>}</div><div className="insight"><div className="insight-icon blue"><ShieldCheck size={20}/></div><div><span>清楚知道，哪些还未知</span><strong>{plan?`${plan.sources.length} 个来源记录`:'先证据，后建议'}<small>开放 · 天气 · 构图分开核验</small></strong></div></div></div>
            <div className="field-note"><span>FIELD NOTE / 001</span><p>好的照片，始于按下快门之前。</p><Aperture size={30} strokeWidth={1}/></div>
          </div>
        </div>

        {busy&&<section className="progress-card" aria-live="polite"><div><LoaderCircle className="spin" size={18}/><b>正在寻找值得拍的机位</b><small>只展示实际执行步骤</small></div><ol>{events.map((e,i)=><li key={i}><Check size={14}/>{e.message}</li>)}</ol></section>}

        <section ref={resultRef} className="results">
          <div className="result-heading"><div><span className="eyebrow muted">YOUR FIELD GUIDE</span><h2>{plan?(plan.brief.intent.recommendation_mode==='best'?'拍摄建议 · 最佳机位':'拍摄建议 · 推荐机位'):'下一帧，正在等你'}</h2>{plan&&<p>{plan.brief.destination} · {plan.brief.travel_date} · {plan.brief.timezone} <span className="version">V{plan.version}</span></p>}</div>{plan&&<div className="result-actions"><button className="secondary" onClick={refresh} disabled={working}><CloudSun size={15}/>刷新天气</button><button className="secondary" onClick={undo} disabled={plan.version<=1||working}><RotateCcw size={15}/>撤销修改</button><button className="secondary" onClick={exportPlan}><ArrowDownToLine size={15}/>导出发现</button></div>}</div>
          <div className="result-tabs"><div><button className={tab==='spots'?'active':''} onClick={()=>setTab('spots')}>推荐机位 {plan&&<span>{plan.agent_answer?.candidates.length||new Set(active.map(t=>t.spot_id)).size}</span>}</button><button className={tab==='sources'?'active':''} onClick={()=>setTab('sources')}>证据与来源 {plan&&<span>{plan.sources.length}</span>}</button><button className={tab==='notes'?'active':''} onClick={()=>setTab('notes')}>发现说明</button></div><span className="draft-pill"><i/>{plan?.brief.mode==='live'?'联网草案 · 待现场确认':'离线 Demo · 数据明确标注'}</span></div>
          {!plan?<div className="empty-state"><div className="empty-icon"><Compass size={31} strokeWidth={1.2}/></div><h3>你负责想象，我们负责侦察。</h3><p>选择左侧的南京灵感场景，或写下自己的拍摄想法。<br/>确认后，机位、光线、器材和依据会在这里汇合。</p><button onClick={()=>seed('cityscape')}>试试「蓝调时刻的南京」<ArrowUpRight size={15}/></button></div>:
          tab==='spots'?<><ShootingTimeline plan={plan}/><RecreationResult key={plan.id} plan={plan}/><div className="task-list">{cardTasks.map((task,i)=><TaskCard key={task.id} task={task} candidate={candidateBySpot.get(task.spot_id)} number={i+1} plan={plan} selected={selected===task.spot_id} onSelect={()=>setSelected(task.spot_id)} cite={cite} change={change} working={working}/>)}</div>{pendingCandidates.length>0&&<div className="candidate-leads">{pendingCandidates.map((candidate,i)=><CandidateLeadCard key={candidate.id} candidate={candidate} number={cardTasks.length+i+1} plan={plan}/>)}</div>}{!plan.tasks.length&&!pendingCandidates.length&&<div className="notice">暂时没有可展示的推荐机位，请查看发现说明并调整地点或拍摄条件。</div>}{!structuredCandidates.length&&!!plan.agent_answer?.summaries.length&&<details className="brief-supplement"><summary>补充说明</summary>{plan.agent_answer.summaries.map((summary,i)=><p key={i}>{summary}</p>)}</details>}</>:
          tab==='sources'?<div className="sources-grid">{plan.sources.map(source=><article key={source.id} className="source-card"><span className={`tag ${source.kind==='official'?'green':''}`}>{source.platform || kinds[source.kind]}</span><h3>{source.title}</h3><p>{source.note||'记录本次规划的数据来源与规则依据。'}</p><small>获取：{new Date(source.retrieved_at).toLocaleString('zh-CN')}<br/>发布：{source.published_at?new Date(source.published_at).toLocaleDateString('zh-CN'):'未提供 / 不适用'}</small><div><button onClick={()=>setDrawer(plan.evidence.filter(e=>e.source_id===source.id))}>查看关联证据 ↗</button>{source.url&&<a href={source.url} target="_blank" rel="noreferrer">原始来源 <ExternalLink size={12}/></a>}</div></article>)}</div>:
          <div className="notes"><h3><Info size={18}/>出发前，再确认一次</h3>{plan.warnings.map((w,i)=><p key={i}>{w}</p>)}{plan.excluded.length>0&&<><h3>未纳入当前候选</h3>{plan.excluded.map((e,i)=><p key={i}><b>{e.spot}</b>：{e.reason}</p>)}</>}<h3>本次运行记录</h3><p>耗时 {String(plan.metrics.elapsed_ms)} ms · Provider 调用 {String(plan.metrics.provider_calls)} 次 · {String(plan.metrics.cost_note)}</p><p>Live 接口状态：百炼 {health?.dashscope_configured?'已配置':'未配置'} / 高德 {health?.amap_configured?'已配置':'未配置'}。配置存在不等于账户或接口已通过联网验证。</p></div>}
        </section>
        <footer><span><Aperture size={14}/> PhotoScout</span><span>让每一次出发，都更接近你想要的画面。</span><span>MADE FOR THE WANDERING EYE</span></footer>
      </div>
    </main>

    {confirm&&reviewBook&&<BriefConfirmation brief={brief} book={reviewBook} working={working} onChange={patch} onClose={()=>setConfirm(false)} onResolve={resolveLocation} onApprove={approveBrief} onSelect={location=>{setBrief(b=>({...b,location}));setReviewBook(b=>b?{...b,location_status:'confirmed',location_choices:[],questions:[]}:b);}}/>}

    {drawer&&plan&&<div className="overlay drawer-overlay" onClick={()=>setDrawer(null)}><aside className="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="evidence-title" onClick={e=>e.stopPropagation()}><button className="close" aria-label="关闭证据" onClick={()=>setDrawer(null)}><X size={20}/></button><div className="eyebrow muted">FOLLOW THE EVIDENCE</div><h2 id="evidence-title">这条建议，从何而来？</h2><p className="drawer-intro">把事实、推断和未知分开看。</p>{drawer.map(e=>{const source=plan.sources.find(s=>s.id===e.source_id);return <article className="evidence-item" key={e.id}><span className="tag">{labels[e.label]||e.label}</span><h3>{source?.title}</h3><p>{e.statement}</p>{Object.keys(e.values).length>0&&<pre>{JSON.stringify(e.values,null,2)}</pre>}<small>记录于 {new Date(e.observed_at).toLocaleString('zh-CN')}</small>{source?.url&&<a href={source.url} target="_blank" rel="noreferrer">查看原始来源 <ExternalLink size={13}/></a>}</article>;})}</aside></div>}

    {proposal&&<div className="overlay"><section className="modal proposal-modal" role="dialog" aria-modal="true" aria-labelledby="proposal-title"><div className="eyebrow muted">REPLAN PROPOSAL</div><h2 id="proposal-title">环境变了，选择由你决定。</h2><p>{proposal.reason}</p><div className="notice">正式计划尚未修改。批准后保存新版本，其他任务保持不变。</div><div className="diff-list">{proposal.diff.filter(d=>d.path.startsWith('/tasks')||d.path.startsWith('/spots')).map((d,i)=><div key={i}><code>{d.path}</code><div className="diff-before">− {JSON.stringify(d.before)}</div><div className="diff-after">+ {JSON.stringify(d.after)}</div></div>)}</div><div className="modal-actions"><button className="secondary" disabled={working} onClick={()=>decide(false)}>拒绝，保留原计划</button><button className="primary" disabled={working} onClick={()=>decide(true)}><Check size={17}/>批准并保存</button></div></section></div>}

    {positionEdit&&<div className="overlay"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="position-title"><button className="close" aria-label="关闭坐标确认" onClick={()=>setPositionEdit(null)}><X size={20}/></button><div className="eyebrow muted">ON-SITE NOTE</div><h2 id="position-title">记录公开区域的位置</h2><p>{positionEdit.name} · 先在地图与现场核对，坐标记录不会解除开放或安全门控。</p><label>空间角色<select aria-label="空间角色" value={positionEdit.role} onChange={e=>setPositionEdit({...positionEdit,role:e.target.value})}><option value="camera">相机站位</option><option value="entrance">公开入口</option></select></label><div className="field-row"><label>纬度 · WGS84<input type="number" step="0.000001" aria-label="确认纬度" value={positionEdit.lat} onChange={e=>setPositionEdit({...positionEdit,lat:Number(e.target.value)})}/></label><label>经度 · WGS84<input type="number" step="0.000001" aria-label="确认经度" value={positionEdit.lon} onChange={e=>setPositionEdit({...positionEdit,lon:Number(e.target.value)})}/></label></div><div className="notice">预填坐标为近似区域中心，不代表精确拍摄位置。请填写你核对过的 WGS84 坐标；高德原始 GCJ-02 坐标不能直接粘贴。</div><button className="primary" disabled={working} onClick={confirmPosition}>生成位置修改提案 <ArrowRight size={16}/></button></section></div>}

          {showHistory&&<div className="overlay" onClick={()=>setShowHistory(false)}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="history-title" onClick={e=>e.stopPropagation()}><button className="close" aria-label="关闭历史" onClick={()=>setShowHistory(false)}><X size={20}/></button><div className="eyebrow muted">YOUR COLLECTION</div><h2 id="history-title">我的发现</h2>{history.length?history.map(h=><button className="history-row" key={h.id} onClick={async()=>{try{const p=await api<Plan>(`/plans/${h.id}`);setPlan(p);setSelected(p.tasks[0]?.spot_id||'');setProposal(null);setShowHistory(false);}catch(e){setError((e as Error).message);}}}><MapPin size={18}/><span>{h.destination}<small>{h.date} · {h.categories.length?h.categories.map(c=>categoryLabels[c]||c).join(' / '):'未限定题材'} · V{h.version}</small></span><ArrowRight size={17}/></button>):<p>还没有已保存计划，先生成一次南京 Demo 吧。</p>}</section></div>}
  </div>;
}

function TaskCard({task,candidate,number,plan,selected,onSelect,cite,change,working}: {task:Task;candidate?:AgentCandidate;number:number;plan:Plan;selected:boolean;onSelect:()=>void;cite:(ids:string[])=>void;change:(task:Task,reason:string)=>void;working:boolean}) {
  const spot=plan.spots.find(s=>s.id===task.spot_id)!;
  const shutter=task.camera.shutter_seconds>=1?`${task.camera.shutter_seconds}s`:`1/${Math.round(1/task.camera.shutter_seconds)}s`;
  const sourceLinks=plan.sources.filter(source=>candidate?.source_ids.includes(source.id)&&source.url);
  const directions=Object.entries(task.subject_bearings_deg||{});
  const mapLabel=spot.camera.precision==='EXACT_VERIFIED'?'位置已确认':spot.viewpoint_status==='mapped_viewpoint'?'地图已定位':'区域已定位';
  return <article className={`task-card ${selected?'selected':''} ${task.status==='CANCELLED'?'cancelled':''}`}>
    <div className="task-number"><span>#{candidate?.rank||number}</span></div><div className="task-main"><div className="task-topline"><div className="candidate-status"><span className="tag green">{mapLabel}</span><span className={`tag ${directions.length?'green':'amber'}`}>{directions.length?'方向已核验':'方向待确认'}</span>{task.status==='CANCELLED'&&<span className="tag red">当前暂缓</span>}</div><button className="task-location" onClick={onSelect}><MapPin size={13}/>在图上查看</button></div><h3>{candidate?.name||spot.name}</h3><p className="candidate-subtitle">{candidate?.selection_reason||task.reasons?.[0]||'根据拍摄目标、时间和器材综合推荐'}</p><PhotoGallery spot={spot} planId={plan.id}/>
    <div className="advice-grid">
      <section><h4><Clock3 size={14}/>推荐拍摄时间</h4><b>{localTime(task.start,plan.brief.timezone)}–{localTime(task.end,plan.brief.timezone)}</b><p>{candidate?.recommended_time||({daylight:'日间',golden_hour:'黄金时刻',blue_hour:'蓝调时刻',night:'夜间'} as Record<string,string>)[task.recommended_light||'']||'按现场条件判断'}</p>{candidate?.time_judgment&&<p>{candidate.time_judgment}</p>}</section>
      <section><h4><Compass size={14}/>取景方向与构图</h4><b>{directions.length?directions.map(([name,value])=>`${name} ${value}° · ${task.subject_distances_km?.[name] ?? '距离待确认'}${task.subject_distances_km?.[name] === undefined?'':' km'}`).join('；'):candidate?.shooting_direction||'方向待现场确认'}</b><p>{candidate?.composition||task.composition}</p>{task.framing_assessment&&<p>{task.framing_assessment}</p>}</section>
      <section><h4><Camera size={14}/>焦段与器材</h4><b>{task.camera.lens} · {task.camera.equivalent_mm}mm 等效</b><p>{candidate?.equipment_advice||task.camera.adjustment}</p></section>
      <section><h4><Footprints size={14}/>到达与站位</h4><b>{candidate?.camera_location?.display_name||spot.name}</b><p>{candidate?.camera_instruction||spot.camera_instruction||'精确站位待现场确认'}</p><p>{task.travel_advice?.[0]}</p></section>
    </div>
    <div className="camera-strip"><div><Camera size={15}/><b>参数建议</b><small>现场测光起点</small></div><div><span>焦段</span><b>{candidate?.settings_advice?.focal_length||`${task.camera.equivalent_mm}mm 等效`}</b></div><div><span>光圈</span><b>{candidate?.settings_advice?.aperture||`f/${task.camera.aperture}`}</b></div><div><span>快门</span><b>{candidate?.settings_advice?.shutter||shutter}</b></div><div><span>ISO</span><b>{candidate?.settings_advice?.iso||task.camera.iso}</b></div><button onClick={()=>cite(task.camera.evidence_ids)}>计算依据 ↗</button></div>
    <div className="task-signals"><button onClick={()=>cite(task.weather.evidence_ids)}><CloudSun size={15}/>{task.weather.temperature_c===null?'天气待确认':`${task.weather.temperature_c}°C · 风 ${task.weather.wind_kmh ?? '未知'} km/h`}<span>{labels[task.weather.label]}</span></button><button onClick={()=>cite(task.crowd.evidence_ids)}><Users size={14}/>客流待确认</button><button onClick={()=>cite(task.score.evidence_ids)}>适配 {task.score.suitability}<span>核验置信度 {Math.round(task.score.confidence*100)}%</span></button></div>
    <details className="task-details"><summary>出发前确认与参考来源<ChevronDown size={14}/></summary><div>{[...(task.alerts||[]),...task.risks].filter((text,index,list)=>list.indexOf(text)===index).map((text,i)=><p key={i}>• {text}</p>)}<p>{candidate?.verification_note}</p><button className="tiny-link" onClick={()=>cite(task.evidence_ids)}>查看核验依据 ↗</button>{sourceLinks.map(source=><p key={source.id}><a href={source.url!} target="_blank" rel="noreferrer">{source.title} <ExternalLink size={11}/></a></p>)}</div></details>
    {task.status!=='CANCELLED'&&<div className="task-actions"><span><ShieldCheck size={13}/>条件改变后，先提议再保存</span><button disabled={working} onClick={()=>change(task,plan.brief.mode==='mock'?'模拟降雨：暂缓该机位拍摄':'用户反馈天气恶化：暂缓该机位')}>天气变差</button><button disabled={working} onClick={()=>change(task,plan.brief.mode==='mock'?'模拟开放变化：入口未确认，暂缓该机位':'用户反馈入口或开放不确定：暂缓该机位')}>开放有变化</button></div>}
    </div>
  </article>;
}

function CandidateLeadCard({candidate,number,plan}:{candidate:AgentCandidate;number:number;plan:Plan}) {
  const sources=plan.sources.filter(source=>candidate.source_ids.includes(source.id)&&source.url);
  const status:Record<string,string>={area:'区域已定位',map_only:'地图已定位',unlocated:'位置待确认',rejected:'暂不采用',mapped:'地图已定位'};
  return <article className="task-card lead-card"><div className="task-number"><span>#{candidate.rank||number}</span></div><div className="task-main">
    <div className="task-topline"><div className="candidate-status"><span className={`tag ${candidate.verification_status==='rejected'?'red':'amber'}`}>{status[candidate.verification_status]}</span><span className="tag amber">方向待确认</span></div></div>
    <h3>{candidate.name}</h3><p className="candidate-subtitle">{candidate.selection_reason||'值得继续核对的拍摄位置'}</p>
    <div className="advice-grid"><section><h4><Clock3 size={14}/>推荐拍摄时间</h4><b>{candidate.recommended_time||'按现场光线判断'}</b><p>{candidate.time_judgment}</p></section><section><h4><Compass size={14}/>取景方向与构图</h4><b>{candidate.shooting_direction||'方向待确认'}</b><p>{candidate.composition}</p></section><section><h4><Camera size={14}/>焦段与器材</h4><b>{candidate.settings_advice.focal_length||'根据现场距离选择'}</b><p>{candidate.equipment_advice}</p></section><section><h4><Footprints size={14}/>到达与站位</h4><b>{candidate.camera_location?.display_name||candidate.name}</b><p>{candidate.camera_instruction||'具体站位待地图与现场确认'}</p></section></div>
    {Object.keys(candidate.settings_advice).length>0&&<div className="agent-settings">{Object.entries(candidate.settings_advice).map(([key,value])=><span key={key}><small>{key}</small>{value}</span>)}</div>}
    <div className="candidate-alerts"><b>出发前确认</b><p>{candidate.verification_note}</p></div>
    {!!sources.length&&<details className="task-details"><summary>参考来源<ChevronDown size={14}/></summary>{sources.map(source=><p key={source.id}><a href={source.url!} target="_blank" rel="noreferrer">{source.title} <ExternalLink size={11}/></a></p>)}</details>}
  </div></article>;
}
