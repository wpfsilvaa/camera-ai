// Tela do totem: a saudação aparece POR CIMA (sem empurrar os botões) com blur, e usa os textos personalizados.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import assert from 'node:assert/strict';
const base='http://127.0.0.1:18097';
const server=spawn('python3',['-m','http.server','18097','--bind','127.0.0.1'],{cwd:'notebook/kiosk',stdio:'ignore'});
let browser;
const weather=(over={})=>({at:Date.now()/1000,t:27,text:'Parcialmente nublado',icon:'cloud',days:[{hi:28,lo:19,rain:10}],...over});
const state=(extra={})=>({vigia:'resting',night:false,red:false,present:['Flavio'],call:{state:'idle',seq:1},enabled:{call:true,panic:true},linked:true,greet:{id:'g1',name:'Flavio',daily:true,quiet:false},bdays:[],callto:[],reminders:[],battery:80,plugged:true,...extra});
async function open(payload){
  const page=await browser.newPage({viewport:{width:1366,height:768}});
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
  assert.match(sub,/Hoje é .*Agora faz 27° e o tempo está parcialmente nublado\. Máxima de 28° e mínima de 19°\. Sugestão: bom dia para uma caminhada leve\./,sub);
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
  assert.match(none,/^Hoje é [^.]*\. Sugestão: lembre-se de beber água ao longo do dia\.$/,none);
  await page.close();
  console.log('PASS: saudação por cima com blur, sem mexer nos botões; textos personalizados, chuva, sem sugestões e sem previsão.');
} finally { await browser?.close(); server.kill(); }
