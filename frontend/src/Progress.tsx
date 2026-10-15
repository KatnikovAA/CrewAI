import { useEffect, useState } from 'react';
import { duration, taskNames } from './domain';
import type { ProgressEvent, TaskName, TripState } from './types';
import type { PollIssue } from './useTrip';
const statuses={queued:'В очереди',running:'Команда работает',completed:'Маршрут готов',failed:'Команда завершилась с ошибкой'};
const tools:Record<string,string>={internet_search:'Поиск источников',website_reader:'Чтение страницы',trip_cost_calculator:'Расчёт расходов'};
function eventLabel(event:ProgressEvent){
  if(event.tool)return `${tools[event.tool]||'Инструмент'} · ${event.type==='tool_started'?'начат':event.status==='ok'?'готово':event.status==='empty'?'нет данных':'ошибка'}${event.from_cache?' · из кеша':''}`;
  const labels:Record<string,string>={queued:'Запуск принят',run_started:'Команда запущена',run_completed:'Результат проверен',run_failed:'Запуск завершён с ошибкой',task_started:'Задача начата',task_completed:'Задача завершена',task_failed:'Задача прервана',llm_request:'Запрос к модели',llm_response:'Получен ответ модели',validation_failed:'Ответ не прошёл проверку'};
  return `${event.task?taskNames[event.task]+' · ':''}${labels[event.type]||'Событие выполнения'}`;
}
export function Progress({tripId,state,issue,resume}:{tripId:string|null;state:TripState|null;issue:PollIssue|null;resume:()=>void}){
  const [clock,setClock]=useState(Date.now());
  useEffect(()=>{if(!state||!['queued','running'].includes(state.status))return;const timer=setInterval(()=>setClock(Date.now()),1000);return()=>clearInterval(timer)},[state?.status]);
  const seconds=state?Math.max(0,Math.floor(((state.finished_at?Date.parse(state.finished_at):clock)-Date.parse(state.started_at||state.created_at))/1000)):0;
  const steps=Object.keys(taskNames) as TaskName[];
  return <section className="panel progress-panel" aria-labelledby="progress-title"><div className="section-top"><span className="eyebrow">02 / Выполнение</span>{state&&<span className="quiet">{duration(seconds)}</span>}</div><div className="progress-heading"><h2 id="progress-title">{tripId?'Ваша команда':'От идеи до маршрута'}</h2>{state&&<span className={`status-tag ${state.status}`} aria-live="polite">{statuses[state.status]}</span>}</div>
    <p className="section-intro">{!tripId?'Исследователь, специалист по бюджету и планировщик работают последовательно.':state?.current_task?`Сейчас: ${taskNames[state.current_task].toLowerCase()}.`:'Состояние и события приходят с сервера.'}</p>
    <ol className="steps">{steps.map((key,index)=>{const done=state?.status==='completed'||state?.events.some(e=>e.task===key&&e.type==='task_completed');const failed=state?.events.some(e=>e.task===key&&e.type==='task_failed');const active=state?.status==='running'&&state.current_task===key;return <li key={key} className={done?'done':failed?'broken':active?'active':''}><span className="step-number" aria-hidden="true">{done?'✓':String(index+1).padStart(2,'0')}</span><div><strong>{taskNames[key]}</strong><small>{done?'Завершено':failed?'Прервано':active?'Выполняется':tripId?'Ожидает':'После отправки формы'}</small></div></li>})}</ol>
    {!tripId&&<div className="empty-state"><span aria-hidden="true">↗</span><h3>Сначала задайте поездку</h3><p>Здесь появятся подтверждённые события, а затем — ваш маршрут. Ничего не запускается автоматически.</p></div>}
    {tripId&&!state&&!issue&&<p className="loading" role="status">Получаем состояние поездки…</p>}
    {issue&&<div className="notice warning" role="alert"><strong>{issue.kind==='missing'?'Запись поездки не найдена':'Наблюдение приостановлено'}</strong><p>{issue.message}</p>{issue.kind!=='missing'&&<button className="secondary" onClick={resume}>Возобновить наблюдение</button>}</div>}
    {state?.status==='failed'&&<div className="notice error" role="alert"><strong>Не удалось получить проверенный маршрут</strong><p>{state.error?.message||'Команда завершилась без результата.'}</p><small>Новый запуск выполняется только по вашему действию.</small></div>}
    {state&&state.events.length>0&&<details className="event-details"><summary>Журнал выполнения <span>{state.events_total} событий</span></summary><p className="quiet">Последние {Math.min(30,state.events.length)} подтверждённых событий. Номера назначает сервер.</p><ol className="events">{state.events.slice(-30).reverse().map(event=><li key={event.seq}><time dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}</time><span>{eventLabel(event)}</span><small>#{event.seq}</small></li>)}</ol></details>}
  </section>;
}
