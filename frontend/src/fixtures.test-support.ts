import type { TripResult, Finding } from './types';
const finding:Finding={text:null,kind:'unknown',sources:[],note:'Нет подтверждения'};
export function resultFixture():TripResult {
 const final:TripResult['final']={days:[{date:'2026-11-14',place_ids:['p1'],schedule:{...finding,text:'Посещение музея',kind:'estimate'},movements:finding}],currency:'RUB',known_total:'40.00',complete:false,budget_status:'undetermined',over_budget:'0',sources:['https://example.com/source','javascript:alert(1)'],caveats:['Уточните билеты']};
 return {trip_id:'abc',final,tasks:{itinerary:final,research:{places:[{id:'p1',name:'Городской музей',description:finding,conditions:finding,hours:finding,price:{amount:null,currency:null,kind:'unknown',sources:[],note:'Нет цены'}}],uncertainties:['Нет расписания']},budget:{currency:'RUB',known_total:'40.00',complete:false,expenses:[{id:'a',name:'Транспорт',category:'transport',amount:'40.00',kind:'estimate',sources:[],note:'Оценка',place_ids:[]},{id:'b',name:'Билеты',category:'activities',amount:null,kind:'unknown',sources:[],note:'Требует проверки',place_ids:['p1']}],logistics:[finding],assumptions:['Цены ориентировочные']}}};
}
