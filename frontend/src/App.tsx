import { useEffect, useRef, useState } from 'react';
import { ApiError, createTrip, readTripId, rememberTrip, request, validationErrors } from './api';
import { buildTrip, initialDraft } from './domain';
import { Progress } from './Progress';
import { ResultView } from './ResultView';
import { TripForm } from './TripForm';
import { useTrip } from './useTrip';
import type { Draft, FieldErrors } from './types';
export default function App(){
  const [draft,setDraft]=useState<Draft>(initialDraft),[errors,setErrors]=useState<FieldErrors>({}),[tripId,setTripId]=useState(readTripId);
  const [submitting,setSubmitting]=useState(false),[submitError,setSubmitError]=useState(''),[health,setHealth]=useState('Проверяем API');
  const gate=useRef(false),mounted=useRef(true),postController=useRef<AbortController|null>(null);
  const {state,result,issue,resume}=useTrip(tripId);
  useEffect(()=>{mounted.current=true;const controller=new AbortController();void request<{status:string}>('/health',{},controller.signal).then(()=>{if(!controller.signal.aborted)setHealth('API доступен')}).catch(()=>{if(!controller.signal.aborted)setHealth('API недоступен')});return()=>{mounted.current=false;controller.abort();postController.current?.abort()}},[]);
  async function submit(){
    if(gate.current||tripId)return;
    const checked=buildTrip(draft);setErrors(checked.errors);setSubmitError('');
    if(!checked.data){queueMicrotask(()=>document.getElementById(`field-${Object.keys(checked.errors)[0]}`)?.focus());return}
    gate.current=true;setSubmitting(true);const controller=new AbortController();postController.current=controller;
    try {
      const accepted=await createTrip(checked.data,controller.signal);
      if(!mounted.current)return;
      if(!/^[a-zA-Z0-9-]{1,128}$/.test(accepted.trip_id))throw new Error('Invalid identifier');
      rememberTrip(accepted.trip_id);setTripId(accepted.trip_id);
    } catch(error){
      if(!mounted.current)return;
      if(error instanceof ApiError&&error.status===422){setErrors(validationErrors(error));setSubmitError('Сервер отклонил параметры. Проверьте отмеченные поля и даты поездки.')}
      else if(error instanceof ApiError&&error.status===409)setSubmitError('Сервер уже выполняет поездку. Дождитесь её завершения перед новым запуском.');
      else if(error instanceof ApiError&&error.status===503)setSubmitError('Сервер завершает работу. Повторите отправку после его запуска.');
      else setSubmitError('Не удалось получить подтверждение запуска. Запуск мог быть принят сервером: не отправляйте параметры повторно, пока не убедитесь, что предыдущая поездка не выполняется.');
    } finally {gate.current=false;if(mounted.current)setSubmitting(false)}
  }
  function newTrip(){rememberTrip(null);setTripId(null);setErrors({});setSubmitError('');queueMicrotask(()=>document.getElementById('field-departure_city')?.focus())}
  const canStartNew=!!tripId&&(state?.status==='completed'||state?.status==='failed'||issue?.kind==='missing');
  return <><a className="skip-link" href="#main">Перейти к поездке</a><header className="site-header"><a className="brand" href="#main" aria-label="Путь — планировщик путешествий"><span className="brand-mark" aria-hidden="true">↗</span><span>путь<span className="brand-caption">планировщик путешествий</span></span></a><nav className="header-nav" aria-label="Навигация"><a href="#form-title">Спланировать поездку</a><a href="#progress-title">Как это работает</a></nav><span className="local-label">Локальная версия <span className="api-health" title="Доступность модели и поиска не проверялась">{health}</span></span></header><main id="main"><div className="page-heading"><div className="hero-landscape" aria-hidden="true"><span className="sun"/><span className="hill hill-back"/><span className="hill hill-front"/><span className="road"/></div><div><span className="eyebrow">Планы начинаются с любопытства</span><h1>А куда вам<br/><em>давно хотелось?</em></h1></div><p>Выберите город, соберите близких и оставьте место для новых впечатлений. С маршрутом и расходами поможем.</p><div className="hero-notes"><span>Маршрут по вашим интересам</span><span>Расходы с источниками</span><span>В вашем темпе</span></div></div><div className="workspace"><div><TripForm draft={draft} errors={errors} disabled={submitting||!!tripId} submitting={submitting} onSubmit={()=>void submit()} onChange={(key,value)=>{setDraft(old=>({...old,[key]:value}));setErrors(old=>({...old,[key]:undefined}))}}/>{submitError&&<div className="notice error submit-error" role="alert">{submitError}</div>}</div><div className="output-column"><Progress tripId={tripId} state={state} issue={issue} resume={resume}/>{canStartNew&&<div className="new-trip"><p>{result?'Маршрут сохранится на экране, пока вы не начнёте новую поездку.':'Можно вернуться к параметрам и начать новый запуск.'}</p><button className="secondary" onClick={newTrip}>Новая поездка</button></div>}{result&&<ResultView result={result}/>}</div></div></main><footer>Путь · Учебный планировщик на CrewAI<span>Источники, оценки и честные пробелы в данных</span></footer></>;
}
