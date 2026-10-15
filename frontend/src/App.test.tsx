import { it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { ResultView } from './ResultView';
import { resultFixture } from './fixtures.test-support';
import { STORAGE_KEY } from './api';
const response=(data:unknown,status=200)=>new Response(JSON.stringify(data),{status});
function fill(){for(const [label,value] of [['Город отправления','Москва'],['Направление','Казань'],['Начало поездки','2026-11-14'],['Окончание поездки','2026-11-15'],['Общий бюджет','60000.0001']] as const)fireEvent.change(screen.getByLabelText(label),{target:{value}})}
it('shows unknown costs, server subtotal and friendly place names without unsafe links',()=>{
 render(<ResultView result={resultFixture()}/>);
 expect(screen.getByText('Недостаточно данных для сравнения с бюджетом')).toBeInTheDocument();
 expect(screen.getByText('Известный подытог')).toBeInTheDocument();expect(screen.getByText('40,00')).toBeInTheDocument();
 expect(screen.getByText('Цена неизвестна')).toBeInTheDocument();expect(screen.getAllByText('Городской музей').length).toBeGreaterThan(0);
 expect(document.querySelector('a[href^="javascript:"]')).toBeNull();expect(screen.getByRole('button',{name:/Скачать JSON/})).toBeVisible();
});
it('shows proven excess even for an incomplete budget',()=>{const data=resultFixture();data.final.budget_status='exceeded';data.final.over_budget='2.25';render(<ResultView result={data}/>);expect(screen.getByText('Превышение: 2,25 RUB')).toBeInTheDocument()});
it.each([409,422])('preserves form values on HTTP %s and maps field errors',async(status)=>{
 const fetcher=vi.fn().mockImplementation((url:string,options:RequestInit)=>options?.method==='POST'?Promise.resolve(response(status===409?{detail:{code:'trip_in_progress'}}:{detail:[{loc:['body','budget'],msg:'Неверный бюджет'}]},status)):Promise.resolve(response({status:'ok'})));
 vi.stubGlobal('fetch',fetcher);render(<App/>);fill();fireEvent.click(screen.getByRole('button',{name:/Составить маршрут/}));
 await screen.findByRole('alert');expect(screen.getByLabelText('Общий бюджет')).toHaveValue('60000.0001');
 const post=fetcher.mock.calls.find(c=>c[1]?.method==='POST');expect(JSON.parse(post![1].body as string).budget).toBe('60000.0001');
 if(status===422)expect(screen.getByText('Неверный бюджет')).toBeInTheDocument();else expect(screen.getByText(/Сервер уже выполняет поездку/)).toBeInTheDocument();
});
it('blocks duplicate POST and persists accepted trip id',async()=>{
 let finish!:(r:Response)=>void;const fetcher=vi.fn().mockImplementation((url:string,opts:RequestInit)=>opts?.method==='POST'?new Promise<Response>(resolve=>{finish=resolve}):Promise.resolve(response(url.endsWith('/health')?{status:'ok'}:{trip_id:'abc',status:'failed',current_task:null,created_at:new Date().toISOString(),started_at:null,finished_at:null,events:[],events_total:0,error:null})));
 vi.stubGlobal('fetch',fetcher);render(<App/>);fill();const button=screen.getByRole('button',{name:/Составить маршрут/});fireEvent.click(button);fireEvent.click(button);expect(fetcher.mock.calls.filter(c=>c[1]?.method==='POST')).toHaveLength(1);
 finish(response({trip_id:'abc',status_url:'/trips/abc',result_url:'/trips/abc/result'},202));await waitFor(()=>expect(localStorage.getItem(STORAGE_KEY)).toBe('abc'));
});
it('restores observation after reload and retains result until explicit new trip',async()=>{
 localStorage.setItem(STORAGE_KEY,'abc');vi.stubGlobal('fetch',vi.fn().mockImplementation((url:string)=>Promise.resolve(response(url.endsWith('/health')?{status:'ok'}:url.endsWith('/result')?resultFixture():{trip_id:'abc',status:'completed',current_task:null,created_at:new Date().toISOString(),started_at:null,finished_at:new Date().toISOString(),events:[],events_total:0,error:null}))));
 render(<App/>);await screen.findByText('Поездка складывается');expect(screen.getByLabelText('Направление')).toBeDisabled();
 await userEvent.click(screen.getByRole('button',{name:'Новая поездка'}));expect(screen.queryByText('Поездка складывается')).not.toBeInTheDocument();expect(localStorage.getItem(STORAGE_KEY)).toBeNull();expect(screen.getByLabelText('Город отправления')).toHaveFocus();
});
