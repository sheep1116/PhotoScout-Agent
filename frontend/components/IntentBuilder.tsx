'use client';
import {Brief, PhotographyIntent} from '@/lib/types';

export const categoryLabels: Record<string,string> = {landscape:'风光',portrait:'人像',humanities:'人文',architecture:'建筑',nature:'自然生态',cityscape:'城市夜景'};
export default function IntentBuilder({brief, onChange}: {brief:Brief; onChange:(patch:Partial<Brief>)=>void}) {
  const intent:PhotographyIntent = brief.intent || {categories:[brief.genre],subjects:[],styles:[],light:'any',mobility:'standard'};
  const update = (patch:Partial<PhotographyIntent>) => {
    const next = {...intent,...patch}; onChange({intent:next,genre:next.categories[0]});
  };
  const toggle = (category:string) => {
    const items = intent.categories.includes(category) ? intent.categories.filter(c=>c!==category) : [...intent.categories,category];
    if(items.length) update({categories:items});
  };
  return <div className="intent-builder">
    <div className="field-label">摄影方向 <small>可多选 · 首项为主要题材</small></div>
    <div className="intent-chips">{Object.entries(categoryLabels).map(([key,label])=><button key={key} aria-pressed={intent.categories.includes(key)} onClick={()=>toggle(key)}>{label}</button>)}</div>
    <details className="gear-details"><summary>组合你的画面与光线</summary><div className="gear-content">
      <label>拍摄主体 <input aria-label="拍摄主体" placeholder="如：湖面、古建筑、人物（逗号分隔）" defaultValue={intent.subjects.join('，')} key={`subjects-${brief.genre}`} onBlur={e=>update({subjects:e.target.value.split(/[,，]/).map(s=>s.trim()).filter(Boolean).slice(0,8)})}/></label>
      <label>画面风格 <input aria-label="画面风格" placeholder="如：电影感、极简、倒影（逗号分隔）" defaultValue={intent.styles.join('，')} key={`styles-${brief.genre}`} onBlur={e=>update({styles:e.target.value.split(/[,，]/).map(s=>s.trim()).filter(Boolean).slice(0,8)})}/></label>
      <label>偏好光线<select aria-label="偏好光线" value={intent.light} onChange={e=>update({light:e.target.value as PhotographyIntent['light']})}>{Object.entries({any:'不限光线',daylight:'日间',sunrise:'日出',golden_hour:'日落黄金时刻',blue_hour:'蓝调',night:'夜间'}).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
      <p className="intent-hint">根据题材与光线发现优秀机位。出行距离、客流、停车等会作为候选信息，交由你判断。</p>
    </div></details>
  </div>;
}
