'use client';
import { useEffect, useRef, useState } from 'react';
import type {Plan} from '@/lib/types';
import {Crosshair, Layers, Navigation} from 'lucide-react';

export default function ScoutMap({plan, selected, onSelect}: {plan: Plan | null; selected: string; onSelect: (id: string)=>void}) {
  const container = useRef<HTMLDivElement>(null);
  const [online, setOnline] = useState(false);
  const [mapFailed, setMapFailed] = useState(false);
  const spots = plan?.spots || [];
  const positions = spots.flatMap(s=>[s.camera,...s.subjects.flatMap(t=>t.position?[t.position]:[])]);
  const lons = positions.map(s=>s.lon), lats = positions.map(s=>s.lat);
  const minLon = positions.length?Math.min(...lons)-.001:118.79, maxLon = positions.length?Math.max(...lons)+.001:118.87;
  const minLat = positions.length?Math.min(...lats)-.001:32.045, maxLat = positions.length?Math.max(...lats)+.001:32.075;
  const point = (lon: number, lat: number) => [85+(lon-minLon)/(maxLon-minLon)*640, 345-(lat-minLat)/(maxLat-minLat)*255];
  useEffect(() => {
    if (!online || !container.current) return;
    let map: import('maplibre-gl').Map | undefined;
    let destroyed = false;
    import('maplibre-gl').then(({default: maplibregl}) => {
      if (destroyed || !container.current) return;
      try {
        map = new maplibregl.Map({container: container.current, center: spots.length ? [spots[0].camera.lon, spots[0].camera.lat] : [118.82,32.06], zoom: 13,
          style: {version: 8, sources: {osm: {type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize:256, attribution:'© OpenStreetMap contributors'}}, layers: [{id:'osm',type:'raster',source:'osm'}]}});
        map.addControl(new maplibregl.NavigationControl(), 'top-right');
        map.on('error', ()=>setMapFailed(true));
        map.on('load', ()=>{
          if (!map) return;
          map.addSource('areas',{type:'geojson',data:{type:'FeatureCollection',features:spots.map(s=>({type:'Feature',properties:{id:s.id},geometry:{type:'Point',coordinates:[s.camera.lon,s.camera.lat]}}))}});
          map.addLayer({id:'areas',type:'circle',source:'areas',paint:{'circle-radius':28,'circle-color':'#d3fb5d','circle-opacity':.4,'circle-stroke-color':'#526d26','circle-stroke-width':2}});
          const lines = (plan?.presentation==='candidates'?[]:plan?.routes)?.filter(r=>r.geometry.length>1).map(r=>({type:'Feature' as const,properties:{},geometry:{type:'LineString' as const,coordinates:r.geometry}})) || [];
          spots.forEach(s=>s.subjects.forEach(target=>{if(target.position) lines.push({type:'Feature',properties:{},geometry:{type:'LineString',coordinates:[[s.camera.lon,s.camera.lat],[target.position.lon,target.position.lat]]}});}));
          map.addSource('relations',{type:'geojson',data:{type:'FeatureCollection',features:lines}});
          map.addLayer({id:'relations',type:'line',source:'relations',paint:{'line-color':'#68763b','line-width':2,'line-dasharray':[3,3]}});
        });
      } catch {setMapFailed(true);}
    }).catch(()=>setMapFailed(true));
    return ()=>{destroyed=true;map?.remove();};
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [online, plan?.id, plan?.version]);
  return <section className="map-panel" aria-label="摄影机位关系地图">
    <div className="map-heading"><span><Navigation size={15}/> {plan?.brief.destination || '等待目的地'}<small> / 区域关系图</small></span><span className="map-badge">WGS84 · 近似区域</span></div>
    <div className="map-canvas">
      <svg viewBox="0 0 820 420" className="offline-map" role="img" aria-label="离线区域示意图，非导航地图">
        <defs><pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse"><path d="M 28 0 L 0 0 0 28" fill="none" stroke="#dcdfd5" strokeWidth=".55"/></pattern><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#83964b"/></marker></defs>
        <rect width="820" height="420" fill="#e8eadd"/><rect width="820" height="420" fill="url(#grid)"/>
        <path d="M 270 -30 Q 440 5 385 88 T 482 181 Q 585 134 715 224 L 860 173 L 860 -20 Z" fill="#d8dfc8"/>
        <path d="M 275 -30 Q 458 2 415 98 T 490 158 T 734 198" fill="none" stroke="#c7d1b5" strokeWidth="2"/>
        <path d="M 315 -25 Q 468 14 449 82 T 519 130 T 771 178" fill="none" stroke="#c7d1b5"/>
        <path d="M 740 0 Q 664 46 736 95 T 806 218 L 830 215 L 840 0" fill="#c8d9d7"/>
        <g fill="none" stroke="#f9faf2" strokeWidth="10"><path d="M 0 365 L 168 314 L 370 285 L 560 211 L 820 226"/><path d="M 155 420 L 194 296 L 268 214 L 340 97 L 335 0"/><path d="M 0 166 L 240 192 L 430 249 L 695 373 L 820 380"/></g>
        <g fill="none" stroke="#d3d5c9" strokeWidth="1"><path d="M 0 365 L 168 314 L 370 285 L 560 211 L 820 226"/><path d="M 155 420 L 194 296 L 268 214 L 340 97 L 335 0"/></g>
        <g fill="#909d78" fontSize="13" letterSpacing="4"><text x="514" y="63">{plan?.brief.intent.categories.includes('cityscape')?'城 市 光 影':plan?.brief.destination||'机 位 关 系 示 意'}</text><text x="45" y="258">区域示意</text></g>
        {(plan?.presentation==='candidates'?[]:plan?.routes)?.map((r,i)=><polyline key={i} points={r.geometry.map(p=>point(p[0],p[1]).join(',')).join(' ')} fill="none" stroke="#8b9c57" strokeWidth="2" strokeDasharray="7 5"/>)}
        {spots.map((s,i)=>{const [x,y]=point(s.camera.lon,s.camera.lat); return <g key={s.id} onClick={()=>onSelect(s.id)} className="map-spot" role="button" tabIndex={0} aria-label={`选择${s.name}`} onKeyDown={e=>{if(e.key==='Enter')onSelect(s.id);}}>
          {s.subjects.filter(t=>t.position).map((t,j)=>{const [tx,ty]=point(t.position!.lon,t.position!.lat);return <g key={j}><line x1={x} y1={y} x2={tx} y2={ty} stroke="#83964b" strokeDasharray="4 5" markerEnd="url(#arrow)"/><rect x={tx-4} y={ty-4} width="8" height="8" fill="#718579"/><text x={tx+12} y={ty} fontSize="11" fill="#6a7861">{t.name}</text></g>;})}
          <circle cx={x} cy={y} r={selected===s.id?31:25} fill="#cae291" fillOpacity=".5" stroke="#82985e" strokeDasharray="3 3"/>
          <circle cx={x} cy={y} r="12" fill={selected===s.id?'#30432b':'#ffffff'}/><text x={x} y={y+4} textAnchor="middle" fontSize="11" fill={selected===s.id?'white':'#34482c'}>{i+1}</text>
          <rect x={x+20} y={y-13} width="118" height="27" rx="5" fill="white" fillOpacity=".9"/><text x={x+28} y={y+5} fontSize="12" fill="#374932">{s.name}</text>
          {s.entrance && <text x={point(s.entrance.lon,s.entrance.lat)[0]} y={point(s.entrance.lon,s.entrance.lat)[1]+30} fill="#59766b" fontSize="12">▣ 用户标记入口</text>}
        </g>;})}
        {!plan && <g><circle cx="425" cy="224" r="45" fill="#c7d997" opacity=".65"/><circle cx="425" cy="224" r="8" fill="#667c3b"/><text x="450" y="228" fill="#526437" fontSize="13">从这里开始，寻找光</text></g>}
      </svg>
      {online && <div ref={container} className="live-map"/>}
      <span className="north">N<br/>↑</span><div className="map-controls"><button title="返回离线区域图" onClick={()=>setOnline(false)}><Crosshair size={18}/></button><button title="加载在线底图" onClick={()=>setOnline(true)}><Layers size={18}/></button></div>
      <div className="map-legend"><span>◌ 站位范围</span><span>◇ 被摄主体</span><span>┄ 相机至主体方向</span><button onClick={()=>setOnline(!online)}>{online?'离线示意图':'加载在线地图'} ↗</button></div>
    </div>
    <div className="map-footnote">{mapFailed?'在线底图加载失败，任务卡与离线区域图仍可使用。':'区域圆圈不是精确站位。离线图仅示意空间关系，不作为导航依据。'}</div>
  </section>;
}
