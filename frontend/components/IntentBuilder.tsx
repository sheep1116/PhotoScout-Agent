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
    <details className="gear-details"><summary>组合你的画面与出行条件</summary><div className="gear-content">
      <label>拍摄主体 <input aria-label="拍摄主体" placeholder="如：湖面、古建筑、人物（逗号分隔）" defaultValue={intent.subjects.join('，')} key={`subjects-${brief.genre}`} onBlur={e=>update({subjects:e.target.value.split(/[,，]/).map(s=>s.trim()).filter(Boolean).slice(0,8)})}/></label>
      <label>画面风格 <input aria-label="画面风格" placeholder="如：电影感、极简、倒影（逗号分隔）" defaultValue={intent.styles.join('，')} key={`styles-${brief.genre}`} onBlur={e=>update({styles:e.target.value.split(/[,，]/).map(s=>s.trim()).filter(Boolean).slice(0,8)})}/></label>
      <label>偏好光线<select aria-label="偏好光线" value={intent.light} onChange={e=>update({light:e.target.value as PhotographyIntent['light']})}>{Object.entries({any:'不限光线',daylight:'日间',sunrise:'日出',golden_hour:'日落黄金时刻',blue_hour:'蓝调',night:'夜间'}).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
      <label>客流偏好<select aria-label="客流偏好" value={brief.crowd_tolerance} onChange={e=>onChange({crowd_tolerance:e.target.value})}><option value="low">尽量少人</option><option value="medium">接受一般客流</option><option value="high">接受热门地点</option></select></label>
      <label>通行要求<select aria-label="通行要求" value={intent.mobility} onChange={e=>update({mobility:e.target.value as PhotographyIntent['mobility']})}><option value="standard">一般步行</option><option value="step_free">必须无台阶（需可达证据）</option></select></label>
      <p className="intent-hint">器材、时间和步行预算会一同交给规划器。客流与无障碍信息不足时会明确说明。</p>
    </div></details>
  </div>;
}
