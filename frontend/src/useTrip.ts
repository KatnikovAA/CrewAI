import { useEffect, useState } from 'react';
import { ApiError, request } from './api';
import type { TripResult, TripState } from './types';
export interface PollIssue {kind:'network'|'missing'|'response';message:string}
export function useTrip(tripId:string|null) {
  const [state,setState]=useState<TripState|null>(null),[result,setResult]=useState<TripResult|null>(null);
  const [issue,setIssue]=useState<PollIssue|null>(null),[revision,setRevision]=useState(0);
  useEffect(()=>{setState(null);setResult(null);setIssue(null)},[tripId]);
  useEffect(()=>{
    if(!tripId)return;
    let stopped=false; let timer:ReturnType<typeof setTimeout>|undefined; const controller=new AbortController();
    setIssue(null);
    async function poll(){
      try {
        const next=await request<TripState>(`/trips/${encodeURIComponent(tripId!)}`,{},controller.signal);
        if(stopped)return; setState(next);
        if(next.status==='completed') {
          const ready=await request<TripResult>(`/trips/${encodeURIComponent(tripId!)}/result`,{},controller.signal);
          if(!stopped)setResult(ready);
        } else if(next.status!=='failed') timer=setTimeout(poll,2000);
      } catch(error) {
        if(stopped)return;
        if(error instanceof ApiError&&error.status===404) setIssue({kind:'missing',message:'История поездки недоступна: сервер мог перезапуститься или удалить старую запись. Можно начать новую поездку.'});
        else setIssue({kind:error instanceof ApiError&&error.status===0?'network':'response',message:'Не удалось получить состояние или результат. Это не означает ошибку команды. Возобновите наблюдение, когда связь восстановится.'});
      }
    }
    void poll();
    return ()=>{stopped=true;clearTimeout(timer);controller.abort()};
  },[tripId,revision]);
  return {state,result,issue,resume:()=>setRevision(value=>value+1)};
}
