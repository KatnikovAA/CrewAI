import type { Accepted, FieldErrors, TripInput } from './types';
export const API_BASE=(import.meta.env.VITE_API_BASE_URL||'http://127.0.0.1:8000').replace(/\/$/,'');
export const STORAGE_KEY=`travel-planner:last-trip:${API_BASE}`;
export class ApiError extends Error {
  constructor(public status:number,public payload:unknown,public kind='server'){super('API request failed')}
}
export async function request<T>(path:string, options:RequestInit={}, signal?:AbortSignal):Promise<T> {
  const controller=new AbortController(); const abort=()=>controller.abort();
  signal?.addEventListener('abort',abort,{once:true}); if(signal?.aborted) controller.abort();
  const timeout=setTimeout(()=>controller.abort(),12000);
  try {
    const response=await fetch(API_BASE+path,{...options,signal:controller.signal,headers:{'Content-Type':'application/json',...options.headers}});
    let payload:unknown; try{payload=await response.json()}catch{throw new ApiError(response.status,null,'response')}
    if(!response.ok) throw new ApiError(response.status,payload);
    return payload as T;
  } catch(error) {
    if(error instanceof ApiError) throw error;
    throw new ApiError(0,null,'network');
  } finally {clearTimeout(timeout);signal?.removeEventListener('abort',abort)}
}
export function createTrip(trip:TripInput,signal?:AbortSignal) {return request<Accepted>('/trips',{method:'POST',body:JSON.stringify(trip)},signal)}
export function validationErrors(error:ApiError):FieldErrors {
  const data=error.payload as {detail?:{loc:(string|number)[];msg:string}[]}; const result:FieldErrors={};
  if(Array.isArray(data?.detail)) for(const item of data.detail){const field=item.loc?.[1];if(typeof field==='string'&&['departure_city','destination','start_date','end_date','budget','currency','travelers','interests'].includes(field)) result[field as keyof FieldErrors]=item.msg;}
  return result;
}
export function readTripId():string|null {try{const value=localStorage.getItem(STORAGE_KEY);return value&&/^[a-zA-Z0-9-]{1,128}$/.test(value)?value:null}catch{return null}}
export function rememberTrip(id:string|null){try{if(id)localStorage.setItem(STORAGE_KEY,id);else localStorage.removeItem(STORAGE_KEY)}catch{/* Browser privacy mode: keep this session working. */}}
