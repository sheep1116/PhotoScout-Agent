export type PhotographyIntent = {categories:string[]; subjects:string[]; styles:string[]; light:'any'|'daylight'|'sunrise'|'golden_hour'|'blue_hour'|'night'; mobility:'standard'|'step_free'};
export type PhotoReference = {id:string;provider:string;source_url:string;title:string;author:string;license:string;retrieved_at:string;captured_at:string|null;relation:'poi'|'nearby';latitude:number|null;longitude:number|null;exif:Record<string,string>;evidence_ids:string[]};
export type Brief = {
  text: string; destination: string; travel_date: string; start_local: string; end_local: string;
  timezone: string; genre: string; intent?:PhotographyIntent | null; profile: string;
  lenses: {name: string; min_mm: number; max_mm: number; max_aperture: number}[];
  sensor: string; tripod: boolean; max_walk_km: number; accept_tickets: boolean;
  crowd_tolerance: string; mode: 'mock' | 'live';
};
export type Position = {lat: number; lon: number; precision: string; evidence_ids: string[]};
export type Spot = {id: string; place: {id:string;name:string;position:Position}; camera_instruction:string;viewpoint_status:string;photo_references:PhotoReference[]; name: string; camera: Position; entrance: Position | null; subjects: {name: string; position: Position | null}[]; access: string; composition: string; risks: string[]};
export type Evidence = {id: string; source_id: string; label: string; statement: string; values: Record<string, unknown>; observed_at: string; valid_until: string | null};
export type Source = {id: string; title: string; url: string | null; kind: string; platform?:string|null; publisher: string; retrieved_at: string; published_at: string | null; note: string};
export type Task = {
  id: string; spot_id: string; title: string; start: string; end: string; status: string; composition: string;
  camera: {lens: string; focal_mm: number; equivalent_mm: number; aperture: number; shutter_seconds: number; iso: number; adjustment: string; evidence_ids: string[]};
  weather: {temperature_c: number | null; wind_kmh: number | null; precipitation_mm: number | null; cloud_pct: number | null; visibility_m: number | null; aqi: number | null; label: string; evidence_ids: string[]};
  score: {suitability: number; confidence: number; components: Record<string, number>; weights: Record<string, number>; evidence_ids: string[]};
  crowd: {level: string; label: string; source_type: string; evidence_ids: string[]};
  risks: string[]; alternative: string; solar_azimuth_deg: number; target_bearing_deg: number | null; evidence_ids: string[];
};
export type Plan = {id: string; version: number; brief: Brief; spots: Spot[]; tasks: Task[]; sources: Source[]; evidence: Evidence[];
  claims: {id: string; statement: string; source_id: string; label: string}[];
  solar: {sunrise: string | null; sunset: string | null; golden_start: string | null; blue_start: string | null; blue_end: string | null; evidence_ids: string[]};
  routes: {from_id: string; to_id: string; distance_m: number | null; duration_min: number | null; geometry: number[][]; label: string; note: string}[];
  warnings: string[]; excluded: {spot: string; reason: string}[]; metrics: Record<string, unknown>;
};
export type Proposal = {id: string; base_version: number; reason: string; diff: {path: string; before: unknown; after: unknown}[]};
export async function api<T>(path: string, data?: unknown, headers?: Record<string,string>): Promise<T> {
  const response = await fetch(`/v1${path}`, data === undefined ? {cache: 'no-store'} : {method: 'POST', headers: {'Content-Type': 'application/json', ...headers}, body: JSON.stringify(data)});
  let body;
  try {body = await response.json();} catch {throw new Error('服务暂时不可用，请确认后端已启动。');}
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '请求失败，请检查输入。');
  return body as T;
}
export function localTime(value: string | null, zone = 'Asia/Shanghai') {
  return value ? new Intl.DateTimeFormat('zh-CN', {hour: '2-digit', minute: '2-digit', timeZone: zone, hour12: false}).format(new Date(value)) : '待确认';
}
