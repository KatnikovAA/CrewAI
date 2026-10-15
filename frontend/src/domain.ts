import type { Draft, FieldErrors, TripInput } from './types';
export const taskNames = { research:'Исследование',budget:'Бюджет',itinerary:'Маршрут' };
export const kindNames = { fact:'По источнику',estimate:'Оценка',unknown:'Нет данных' };
export const initialDraft:Draft={departure_city:'',destination:'',start_date:'',end_date:'',budget:'',currency:'RUB',travelers:'2',interests:''};
export function buildTrip(draft:Draft):{data?:TripInput;errors:FieldErrors} {
  const errors:FieldErrors={}; const budget=draft.budget.trim().replace(',','.');
  if(!draft.departure_city.trim()) errors.departure_city='Укажите город отправления.';
  if(!draft.destination.trim()) errors.destination='Укажите направление.';
  const dateOK=(value:string)=>/^\d{4}-\d{2}-\d{2}$/.test(value)&&!isNaN(Date.parse(value))&&new Date(value).toISOString().slice(0,10)===value;
  if(!dateOK(draft.start_date)) errors.start_date='Укажите дату начала.';
  if(!dateOK(draft.end_date)) errors.end_date='Укажите дату окончания.';
  if(!errors.start_date&&!errors.end_date&&draft.end_date<draft.start_date) errors.end_date='Окончание не может быть раньше начала.';
  if(!/^\d+(?:\.\d{1,30})?$/.test(budget)||budget.replace('.','').length>100) errors.budget='Введите неотрицательную сумму без пробелов и экспоненты.';
  if(!/^[A-Z]{3}$/.test(draft.currency)) errors.currency='Используйте три заглавные латинские буквы.';
  if(!/^[1-9]\d*$/.test(draft.travelers)||!Number.isSafeInteger(Number(draft.travelers))) errors.travelers='Укажите положительное целое число.';
  if(Object.keys(errors).length) return {errors};
  return {errors,data:{...draft,departure_city:draft.departure_city.trim(),destination:draft.destination.trim(),budget,travelers:Number(draft.travelers),interests:draft.interests.split(',').map(x=>x.trim()).filter(Boolean)}};
}
export function formatMoney(value:string):string { const [whole,decimal]=value.split('.'); return whole.replace(/\B(?=(\d{3})+(?!\d))/g,' ')+(decimal===undefined?'':','+decimal); }
export function safeUrl(value:string):string|null {try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password?url.href:null}catch{return null}}
export function dateLabel(value:string):string {return new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(value));}
export function duration(seconds:number):string {return seconds<60?`${seconds} с`:`${Math.floor(seconds/60)} мин ${seconds%60} с`;}
