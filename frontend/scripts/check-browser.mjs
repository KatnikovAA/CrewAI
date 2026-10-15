import { chromium } from 'playwright';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
const live=process.argv.includes('--live');
const root=fileURLToPath(new URL('../../',import.meta.url));
const directory=path.join(root,'results','stage7-ui');await mkdir(directory,{recursive:true});
const report={mode:live?'real_browser':'offline_browser',screens:[],checks:[],errors:[],posts:0};
const browser=await chromium.launch({channel:'msedge',headless:true});
const context=await browser.newContext({viewport:{width:1360,height:1000},locale:'ru-RU',timezoneId:'Europe/Moscow',acceptDownloads:true});
const page=await context.newPage();page.on('pageerror',error=>report.errors.push(error.message));
async function screen(name){await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:path.join(directory,name+'.png'),fullPage:true});report.screens.push(name+'.png')}
async function noOverflow(label){const fit=await page.evaluate(()=>({viewport:innerWidth,content:document.documentElement.scrollWidth}));assert.ok(fit.content<=fit.viewport,`${label}: horizontal overflow`);report.checks.push(label+' no overflow')}
async function fill(){await page.getByLabel('Город отправления',{exact:true}).fill('Москва');await page.getByLabel('Направление',{exact:true}).fill('Казань');await page.getByLabel('Начало поездки',{exact:true}).fill('2026-11-14');await page.getByLabel('Окончание поездки',{exact:true}).fill('2026-11-15');await page.getByLabel('Общий бюджет',{exact:true}).fill('60000.00');await page.getByLabel('Путешественники',{exact:true}).fill('2');await page.getByLabel('Интересы',{exact:true}).fill('архитектура')}
try {
 if(!live){
  let code=409;
  await page.route('http://127.0.0.1:8000/trips',async route=>{report.posts++;assert.equal(typeof route.request().postDataJSON().budget,'string');await route.fulfill({status:code,contentType:'application/json',body:JSON.stringify(code===409?{detail:{code:'trip_in_progress'}}:{detail:[{loc:['body','budget'],msg:'Проверьте сумму бюджета'}]})})});
  await page.goto('http://localhost:5173');await page.getByText('API доступен',{exact:true}).waitFor();await noOverflow('wide 1360');
  await page.keyboard.press('Tab');assert.equal(await page.locator(':focus').innerText(),'Перейти к поездке');
  await page.getByLabel('Город отправления',{exact:true}).focus();await page.keyboard.press('Tab');assert.equal(await page.locator(':focus').getAttribute('id'),'field-destination');
  assert.notEqual(await page.locator(':focus').evaluate(el=>getComputedStyle(el).outlineStyle),'none');report.checks.push('keyboard navigation and visible focus');
  await fill();await screen('wide-form');await page.getByRole('button',{name:'Составить маршрут'}).click();await page.getByText(/Сервер уже выполняет поездку/).waitFor();assert.equal(await page.getByLabel('Направление',{exact:true}).inputValue(),'Казань');report.checks.push('409 preserves form and money string');
  code=422;await page.getByRole('button',{name:'Составить маршрут'}).click();await page.getByText('Проверьте сумму бюджета',{exact:true}).waitFor();report.checks.push('422 field error');
  await page.setViewportSize({width:390,height:844});await noOverflow('narrow 390');await screen('narrow-error');
  const fixture=JSON.parse(await readFile(path.join(root,'results/stage6-http-c7299ce466ab.json'),'utf8')).result;fixture.trip_id='fixture-only';
  let polls=0;let releaseLoading;const loadingGate=new Promise(resolve=>{releaseLoading=resolve});const stamp=new Date().toISOString();
  await page.route('http://127.0.0.1:8000/trips/fixture-only',async route=>{polls++;await loadingGate;const status=polls<=2?'queued':polls===3?'running':'completed';await route.fulfill({contentType:'application/json',body:JSON.stringify({trip_id:'fixture-only',status,current_task:status==='running'?'research':null,created_at:stamp,started_at:stamp,finished_at:status==='completed'?stamp:null,events:[],events_total:0,error:null})})});
  await page.route('http://127.0.0.1:8000/trips/fixture-only/result',route=>route.fulfill({contentType:'application/json',body:JSON.stringify(fixture)}));
  await page.evaluate(()=>localStorage.setItem('travel-planner:last-trip:http://127.0.0.1:8000','fixture-only'));await page.reload({waitUntil:'domcontentloaded'});await page.getByText('Получаем состояние поездки…').waitFor();await screen('narrow-loading');releaseLoading();await page.getByRole('heading',{name:'Поездка складывается'}).waitFor({timeout:15000});await noOverflow('narrow result');await screen('narrow-result');
  await page.setViewportSize({width:1360,height:1000});await noOverflow('wide result');await screen('wide-result');
  const download=page.waitForEvent('download');await page.getByRole('button',{name:/Скачать JSON/}).click();const file=await download;await file.saveAs(path.join(directory,'offline-result-download.json'));assert.equal(JSON.parse(await readFile(path.join(directory,'offline-result-download.json'),'utf8')).final.known_total,fixture.final.known_total);report.checks.push('queued/running/completed, restore, loading, incomplete budget and JSON download (mock API only)');
 } else {
  let state=null,result=null,accepted=null;const responses=[];
  page.on('response',response=>{if(!response.url().startsWith('http://127.0.0.1:8000/trips'))return;const pending=(async()=>{const body=await response.json();if(response.request().method()==='POST'){report.posts++;report.post_status=response.status();accepted=body;console.log(JSON.stringify({trip_id:body.trip_id,http:response.status()}))}else if(response.url().endsWith('/result')){report.result_status=response.status();result=body}else{state=body;console.log(JSON.stringify({status:body.status,current_task:body.current_task,events_total:body.events_total}))}})();responses.push(pending)});
  await page.goto('http://localhost:5173');await page.getByText('API доступен',{exact:true}).waitFor();await fill();await screen('real-filled-form');const start=Date.now();await page.getByRole('button',{name:'Составить маршрут'}).click();
  const deadline=Date.now()+450000;let progressShot=false;
  while(Date.now()<deadline){if(state&&['completed','failed'].includes(state.status))break;if(state&&!progressShot){await screen('real-progress');progressShot=true}await new Promise(resolve=>setTimeout(resolve,2000))}
  await Promise.all(responses);report.state=state;report.accepted=accepted;
  assert.equal(state?.status,'completed','Real Crew did not complete');await page.getByRole('heading',{name:'Поездка складывается'}).waitFor({timeout:15000});await Promise.all(responses);
  assert.equal(report.posts,1);assert.equal(report.post_status,202);assert.equal(report.result_status,200);assert.equal(typeof result.final.known_total,'string');
  report.result=result;report.seconds=(Date.now()-start)/1000;await screen('real-wide-result');await noOverflow('real wide result');await page.setViewportSize({width:390,height:844});await noOverflow('real narrow result');await screen('real-narrow-result');
  report.checks.push('real form POST202 → polling → completed → result200, no API mocking');
 }
 assert.deepEqual(report.errors,[]);report.success=true;console.log(JSON.stringify({mode:report.mode,success:true,checks:report.checks}));
} catch(error){report.success=false;report.failure=String(error.message);process.exitCode=1;console.log(JSON.stringify({mode:report.mode,success:false,failure:report.failure}));await screen(live?'real-failure':'offline-failure')}
finally {await writeFile(path.join(directory,live?'real-check.json':'offline-check.json'),JSON.stringify(report,null,2),'utf8');await browser.close()}
