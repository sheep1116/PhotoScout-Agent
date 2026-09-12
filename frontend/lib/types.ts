export type Preferences = {max_walk_km?:number|null;avoid_tickets?:boolean;low_crowd?:boolean;step_free?:boolean;strict?:string[]};
export type PhotographyIntent = {categories:string[];subjects:string[];styles:string[];light:'any'|'daylight'|'sunrise'|'golden_hour'|'blue_hour'|'night';preferences:Preferences;other_requirements?:string[]};
export type DestinationLocation = {id:string;poi_id:string|null;adcode:string;name:string;city:string;address:string;lat:number;lon:number;verification_token:string};
export type Notebook = {brief:Brief;questions:string[];missing_fields:string[];assumptions:string[];recognized:string[];parsed_fields:string[];parser:string;location_choices:DestinationLocation[];location_status:string};
export type PhotoReference = {id:string;provider:string;source_url:string;title:string;author:string;license:string;retrieved_at:string;captured_at:string|null;relation:'poi'|'nearby';latitude:number|null;longitude:number|null;exif:Record<string,string>;evidence_ids:string[]};
export type Brief = {
  reverse_context?:{analysis_id:string;spot_id:string;days:number};
  auto_time_fields?:('start_local'|'end_local'|'end_date')[];
  end_date?:string|null; origin_lat?:number|null; origin_lon?:number|null; text: string; destination: string; travel_date: string; start_local: string; end_local: string;
  timezone: string; intent:PhotographyIntent;location?:DestinationLocation|null;edited_fields?:string[];
  lenses: {name: string; min_mm: number; max_mm: number; max_aperture: number}[];
  sensor: string; tripod: boolean; mode: 'mock' | 'live';
};
export type Position = {lat: number; lon: number; precision: string; evidence_ids: string[]};
export type Spot = {id: string; place: {id:string;name:string;position:Position}; camera_instruction:string;viewpoint_status:string;photo_references:PhotoReference[]; name: string; camera: Position; entrance: Position | null; subjects: {name: string; position: Position | null}[]; access: string; composition: string; risks: string[]};
export type Evidence = {id: string; source_id: string; label: string; statement: string; values: Record<string, unknown>; observed_at: string; valid_until: string | null};
export type Source = {id: string; title: string; url: string | null; kind: string; platform?:string|null; publisher: string; retrieved_at: string; published_at: string | null; note: string};
export type Task = {
  alerts?:string[]; reasons?:string[]; travel_advice?:string[]; distance_km?:number|null;recommended_light?:string;
  id: string; spot_id: string; title: string; start: string; end: string; status: string; composition: string;
  camera: {lens: string; focal_mm: number; equivalent_mm: number; aperture: number; shutter_seconds: number; iso: number; adjustment: string; evidence_ids: string[]};
  weather: {temperature_c: number | null; wind_kmh: number | null; precipitation_mm: number | null; cloud_pct: number | null; visibility_m: number | null; aqi: number | null; label: string; evidence_ids: string[]};
  score: {suitability: number; confidence: number; components: Record<string, number>; weights: Record<string, number>; evidence_ids: string[]};
  crowd: {level: string; label: string; source_type: string; evidence_ids: string[]};
  risks: string[]; alternative: string; solar_azimuth_deg: number; target_bearing_deg: number | null; evidence_ids: string[];
};
export type Plan = {recreation?:{generated_version?:number;photo_id:string;mode:string;visual:{summary:string};location_note:string;difficulties:string[];windows:{date:string;start:string;end:string;match:number;direction_deg:number|null;camera:Task["camera"];differences:string[];equipment:string[]}[]}|null;presentation?:string; id: string; version: number; brief: Brief; spots: Spot[]; tasks: Task[]; sources: Source[]; evidence: Evidence[];
  claims: {id: string; statement: string; source_id: string; subject_id:string; kind:string; evidence_ids:string[]; label: string}[];
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
