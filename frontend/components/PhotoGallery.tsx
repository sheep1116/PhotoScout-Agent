'use client';
import {useState} from 'react';
import {PhotoReference, Spot} from '@/lib/types';

function Preview({photo,planId}: {photo:PhotoReference;planId:string}) {
  const [failed,setFailed] = useState(false);
  return failed ? <div className="photo-unavailable">图片暂时无法加载 · 可查看来源原页</div> :
    // Intentionally use the bounded backend proxy, not Next's general image optimizer.
    // eslint-disable-next-line @next/next/no-img-element
    <img src={`/v1/plans/${encodeURIComponent(planId)}/photos/${encodeURIComponent(photo.id)}`} alt={photo.title} loading="lazy" referrerPolicy="no-referrer" onError={()=>setFailed(true)}/>;
}

export default function PhotoGallery({spot,planId}: {spot:Spot;planId:string}) {
  const photos = spot.photo_references || [];
  const [index,setIndex] = useState(0);
  const [full,setFull] = useState(false);
  const current = photos[index] || photos[0];
  if(!current) return <div className="photo-empty">暂无真实参考图 <span>保留机位线索；不会用生成图片代替实景。</span></div>;
  const platform:Record<string,string>={community:'来源平台',amap:'高德',wikimedia:'Wikimedia',flickr:'Flickr'};
  const badge=current.relation==='source'?'参考样片':current.relation==='nearby'?'附近参考 · 非精确站位样片':'地点实景参考';
  return <section className="photo-gallery" aria-label={`${spot.name}参考样片`}>
    <div className={`photo-cover ${full?'full':''}`}><Preview key={current.id} photo={current} planId={planId}/><span>{badge} · {platform[current.provider]||current.provider}</span></div>
    <div className="photo-caption"><b>{current.title}</b><a href={current.source_url} target="_blank" rel="noopener noreferrer">查看原始来源 ↗</a></div>
    <div className="photo-select" role="group" aria-label="选择参考图片">{photos.map((p,i)=><button key={p.id} aria-pressed={current.id===p.id} onClick={()=>setIndex(i)}>{i+1} · {p.relation==='source'?'参考样片':platform[p.provider]||p.provider}</button>)}<button aria-expanded={full} onClick={()=>setFull(!full)}>{full?'收起完整图片':'展开完整图片'}</button></div>
    <details className="photo-metadata"><summary>作者、授权与拍摄信息</summary><p>作者：{current.author} · 授权：{current.license}</p><p>拍摄时间：{current.captured_at || '未提供'} · 获取时间：{new Date(current.retrieved_at).toLocaleDateString('zh-CN')}</p>{current.latitude!=null&&<p>来源地理标签：{current.latitude}, {current.longitude}（不等于摄影师精确站位）</p>}{Object.keys(current.exif).length>0&&<p>原图 EXIF：{Object.entries(current.exif).map(([k,v])=>`${k}: ${v}`).join(' · ')}</p>}<p>图片仅供构图参考，可能来自其他季节；不证明当前开放、通行或拍摄许可。</p></details>
  </section>;
}
