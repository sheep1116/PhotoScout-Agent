'use client';
import {Brief, PhotographyIntent} from '@/lib/types';

export const categoryLabels: Record<string,string> = {landscape:'风光',portrait:'人像',humanities:'人文',architecture:'建筑',nature:'自然生态',cityscape:'城市夜景'};
export default function IntentBuilder({brief, onChange}: {brief:Brief; onChange:(patch:Partial<Brief>)=>void}) {
  const intent:PhotographyIntent = brief.intent;
  const update = (patch:Partial<PhotographyIntent>) => {
    const next = {...intent,...patch}; onChange({intent:next,edited_fields:[...new Set([...(brief.edited_fields||[]),...Object.keys(patch)])]});
  };
  const toggle = (category:string) => {
    const items = intent.categories.includes(category) ? intent.categories.filter(c=>c!==category) : [...intent.categories,category];
    if(items.length) update({categories:items});
  };
  return <div className="intent-builder">
    <div className="field-label">摄影方向 <small>可多选 · 各方向同等参与</small></div>
    <div className="intent-chips">{Object.entries(categoryLabels).map(([key,label])=><button key={key} aria-pressed={intent.categories.includes(key)} onClick={()=>toggle(key)}>{label}</button>)}</div>
    <details className="gear-details"><summary>组合你的画面与光线</summary><div className="gear-content">
      <label>拍摄主体 <input aria-label="拍摄主体" placeholder="如：湖面、古建筑、人物（逗号分隔）" defaultValue={intent.subjects.join('，')} key={`subjects-${intent.subjects.join()}`} onBlur={e=>update({subjects:e.target.value.split(/[,，]/).map(s=>s.trim()).filter(Boolean).slice(0,8)})}/></label>
      <label>画面风格 <input aria-label="画面风格" placeholder="如：电影感、极简、倒影（逗号分隔）" defaultValue={intent.styles.join('，')} key={`styles-${intent.styles.join()}`} onBlur={e=>update({styles:e.target.value.split(/[,，]/).map(s=>s.trim()).filter(Boolean).slice(0,8)})}/></label>
      <label>偏好光线<select aria-label="偏好光线" value={intent.light} onChange={e=>update({light:e.target.value as PhotographyIntent['light']})}>{Object.entries({any:'不限光线',daylight:'日间',sunrise:'日出',golden_hour:'日落黄金时刻',blue_hour:'蓝调',night:'夜间'}).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
      <fieldset className="preferences"><legend>推荐偏好 · 默认不排除地点</legend>
        <label><input type="checkbox" checked={intent.preferences.max_walk_km!=null} onChange={e=>update({preferences:{...intent.preferences,max_walk_km:e.target.checked?2:null}})}/>低步行量参考</label>
        {intent.preferences.max_walk_km!=null&&<label>参考步行公里数<input aria-label="参考步行公里数" type="number" min="0" max="100" step="0.5" value={intent.preferences.max_walk_km} onChange={e=>update({preferences:{...intent.preferences,max_walk_km:e.target.value===''?null:Math.max(0,Math.min(100,Number(e.target.value)))}})}/></label>}
        <label><input type="checkbox" checked={!!intent.preferences.avoid_tickets} onChange={e=>update({preferences:{...intent.preferences,avoid_tickets:e.target.checked}})}/>优先免费地点</label>
        <label><input type="checkbox" checked={!!intent.preferences.low_crowd} onChange={e=>update({preferences:{...intent.preferences,low_crowd:e.target.checked}})}/>偏好人少</label>
        <label><input type="checkbox" checked={!!intent.preferences.step_free} onChange={e=>update({preferences:{...intent.preferences,step_free:e.target.checked}})}/>优先无台阶通行</label>
        {!!intent.preferences.strict?.length&&<p>描述中含明确要求：{intent.preferences.strict.map(x=>({free:'只推荐免费',step_free:'必须无台阶',low_crowd:'只考虑人少',walking:'明确步行范围'}[x]||x)).join('、')} <button onClick={()=>update({preferences:{...intent.preferences,strict:[]}})}>改为参考偏好</button></p>}
      </fieldset>
      <p className="intent-hint">根据题材与光线发现优秀机位。出行距离、客流、停车等会作为候选信息，交由你判断。</p>
    </div></details>
  </div>;
}
