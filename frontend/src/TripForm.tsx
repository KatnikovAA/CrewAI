import type { Draft, FieldErrors } from './types';
interface Props {draft:Draft;errors:FieldErrors;disabled:boolean;submitting:boolean;onChange:(key:keyof Draft,value:string)=>void;onSubmit:()=>void}
export function TripForm({draft,errors,disabled,submitting,onChange,onSubmit}:Props){
  const field=(key:keyof Draft,label:string,options:{type?:string;hint?:string;placeholder?:string;inputMode?:'decimal'|'numeric'}={})=><div className="field"><label htmlFor={`field-${key}`}>{label}</label><input id={`field-${key}`} name={key} value={draft[key]} type={options.type||'text'} placeholder={options.placeholder} inputMode={options.inputMode} onChange={e=>onChange(key,e.target.value)} disabled={disabled} aria-invalid={!!errors[key]} aria-describedby={errors[key]?`error-${key}`:options.hint?`hint-${key}`:undefined}/>{options.hint&&<small id={`hint-${key}`}>{options.hint}</small>}{errors[key]&&<small className="field-error" id={`error-${key}`}>{errors[key]}</small>}</div>;
  return <section className="panel form-panel" aria-labelledby="form-title"><div className="section-top"><span className="eyebrow">Ваша поездка</span><span className="quiet">Все даты включены</span></div><h2 id="form-title">Куда отправимся?</h2><p className="section-intro">От выходных в соседнем городе до маленького приключения — начнём с ваших планов.</p><form className="trip-fields" noValidate onSubmit={e=>{e.preventDefault();onSubmit()}}>
    {field('departure_city','Город отправления',{placeholder:'Например, Москва'})}
    {field('destination','Направление',{placeholder:'Например, Казань'})}
    <div className="field-row">{field('start_date','Начало поездки',{type:'date'})}{field('end_date','Окончание поездки',{type:'date'})}</div>
    <p className="form-note">Обе даты входят в поездку, включая дорогу туда и обратно. Одинаковые даты — один день.</p>
    {field('budget','Общий бюджет',{inputMode:'decimal',placeholder:'60000.00',hint:'На всю группу и все дни поездки, включая дорогу.'})}
    <div className="field-row">{field('currency','Валюта',{placeholder:'RUB'})}{field('travelers','Путешественники',{inputMode:'numeric'})}</div>
    {field('interests','Интересы',{placeholder:'Архитектура, музеи, местная кухня',hint:'Перечислите через запятую. Поле необязательное.'})}
    <button className="primary wide" type="submit" disabled={disabled}>{submitting?'Отправляем параметры…':'Составить маршрут'}<span aria-hidden="true">↗</span></button>
    <p className="fine-print">Запуск обращается к модели и поиску и расходует лимиты ваших сервисов. Бронирование не выполняется.</p>
  </form></section>;
}
