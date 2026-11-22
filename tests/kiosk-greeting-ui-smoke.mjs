// Tela do totem: a saudação aparece POR CIMA (sem empurrar os botões) com blur, e usa os textos personalizados.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import assert from 'node:assert/strict';
const base='http://127.0.0.1:18097';
const server=spawn('python3',['-m','http.server','18097','--bind','127.0.0.1'],{cwd:'notebook/kiosk',stdio:'ignore'});
let browser;
const weather=(over={})=>({at:new Date('2026-11-22T12:00:00').getTime()/1000,t:27,text:'Parcialmente nublado',icon:'cloud',days:[{hi:28,lo:19,rain:10}],...over});
const NOON=new Date('2026-11-22T12:00:00');   // O texto depende da hora do dia: o relógio da página fica fixo ao meio-dia.
const state=(extra={})=>({vigia:'resting',night:false,red:false,present:['Flavio'],call:{state:'idle',seq:1},enabled:{call:true,panic:true},linked:true,greet:{id:'g1',name:'Flavio',daily:true,quiet:false},bdays:[],callto:[],reminders:[],battery:80,plugged:true,...extra});
async function open(payload){
  const page=await browser.newPage({viewport:{width:1366,height:768}});
  await page.clock.install({time:NOON});
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.route('**/state**',r=>r.fulfill({contentType:'application/json',body:JSON.stringify(payload)}));
  await page.goto(base+'/index.html');
  return {page,errors};
}
try {
  await new Promise(r=>setTimeout(r,800));
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
  // 1) padrão: resumo com clima e sugestão; botões não se mexem; camada com blur
  let {page,errors}=await open(state({weather:weather(),cfg:{}}));
  const before=await page.locator('#btn-call').boundingBox().catch(()=>null);
  await page.waitForSelector('#greeting-sub:not(.hidden)');
  const layer=await page.locator('.greet-layer').evaluate(e=>{const c=getComputedStyle(e);return {position:c.position,blur:c.backdropFilter||c.webkitBackdropFilter,z:c.zIndex};});
  assert.equal(layer.position,'fixed');assert.match(layer.blur,/blur/);
  const after=await page.locator('#btn-call').boundingBox();
  if(before) assert.deepEqual(after,before,'os botões se mexeram quando a saudação apareceu');
  const sub=await page.locator('#greeting-sub').textContent();
  assert.match(sub,/^Hoje é .*\. Agora faz 27° e o céu está parcialmente nublado\. A máxima de hoje é 28° e a mínima, 19°\. O dia está bom para uma caminhada leve\.$/,sub);
  assert.match(await page.locator('#greeting').textContent(),/^(Boa tarde, Flavio!|Oi, Flavio! Boa tarde!|Boa tarde, Flavio, como vai\?)$/);
  await page.waitForTimeout(1300);
  await page.screenshot({path:'test-results/totem-greeting-layer.png'});
  assert.deepEqual(errors,[]);await page.close();
  // 2) textos personalizados e sugestões desligadas; chuva usa o texto de chuva
  ({page,errors}=await open(state({weather:weather({icon:'rain',days:[{hi:24,lo:18,rain:80}]}),cfg:{tips:false,texts:{greet_morning:'Olá {nome}!',greet_afternoon:'Olá {nome}!',greet_night:'Olá {nome}!',daily_rain:'{saudacao}, {nome}. Hoje é {data} e são {hora}. [Chuva: {chuva}.] [Dica: {sugestao}.]'}}})));
  await page.waitForSelector('#greeting-sub:not(.hidden)');
  assert.equal(await page.locator('#greeting').textContent(),'Olá Flavio!');
  const rain=await page.locator('#greeting-sub').textContent();
  assert.match(rain,/^(Bom dia|Boa tarde|Boa noite), Flavio\. Hoje é .* e são \d{2}:\d{2}\. Chuva: 80%\.$/,rain);
  assert.ok(!rain.includes('Dica'),'a sugestão deveria sumir com as sugestões desligadas');
  assert.deepEqual(errors,[]);await page.close();
  // 3) sem previsão: os trechos entre colchetes somem
  ({page,errors}=await open(state({weather:null,cfg:{}})));
  await page.waitForSelector('#greeting-sub:not(.hidden)');
  const none=await page.locator('#greeting-sub').textContent();
  assert.match(none,/^Hoje é [^.]*\. Lembre-se de beber água ao longo do dia\.$/,none);
  await page.close();
  // 4) variações: a mesma saudação (mesmo id) repete a mesma frase; ids diferentes podem sortear outras
  const seen=new Set();
  for(const id of ['g1','g1','g2','g3','g4','g5','g6']){
    const withId=state({greet:{id,name:'Flavio',daily:false,quiet:false},cfg:{texts:{greet_morning:'Alfa {nome}|Beta {nome}|Gama {nome}',greet_afternoon:'Alfa {nome}|Beta {nome}|Gama {nome}',greet_night:'Alfa {nome}|Beta {nome}|Gama {nome}'}}});
    const {page}=await open(withId);await page.waitForSelector('#greeting:not(.hidden)');seen.add(`${id}:${await page.locator('#greeting').textContent()}`);await page.close();
  }
  const byId=[...seen].map(x=>x.split(':')),g1=byId.filter(([id])=>id==='g1');
  assert.equal(g1.length,1,'o mesmo id deveria dar sempre a mesma variação');
  assert.ok(byId.every(([,t])=>/^(Alfa|Beta|Gama) Flavio$/.test(t)));
  assert.ok(new Set(byId.map(([,t])=>t)).size>1,'as variações deveriam variar entre saudações');
  console.log('PASS: saudação por cima com blur, sem mexer nos botões; textos personalizados, chuva, sem sugestões e sem previsão.');
} finally { await browser?.close(); server.kill(); }
