// Histórico: avançar/voltar entre registros (botões, setas do teclado, arrastar no celular, troca de página).
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const data=await mkdtemp(path.join(tmpdir(),'hnav-ui-'));
const base='http://127.0.0.1:18085';
const server=spawn('.venv/bin/python',['tests/history_nav_ui_server.py','18085'],{env:{...process.env,PYTHONPATH:'.',CAMERA_DATA_DIR:data,DASHBOARD_PASSWORD:'',WA_PORT:'18086'},stdio:['ignore','ignore','pipe']});
let logs='',browser;server.stderr.on('data',c=>logs+=c);
try {
  for(let i=0;i<200;i++){try{if((await fetch(base+'/api/settings')).ok)break;}catch{}if(i===199)throw Error(logs);await new Promise(r=>setTimeout(r,200));}
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
  const ctx=await browser.newContext({viewport:{width:1360,height:900},hasTouch:true});
  const page=await ctx.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/');await page.waitForSelector('#day-timeline .tl-mark');
  const spread=await page.evaluate(()=>{const t=document.querySelector('.tl-track').getBoundingClientRect(),l=[...document.querySelectorAll('.tl-ticks span')].map(s=>(s.getBoundingClientRect().left-t.left)/t.width);return l;});
  assert.ok(spread[2]>.4&&spread[2]<.6,'rótulo das 12h deve ficar no meio: '+spread);
  await page.goto(base+'/#history');await page.waitForSelector('#history-table tr');
  const num=()=>page.locator('#event-number').innerText();
  const id=async()=>Number((await num()).match(/#(\d+)/)[1]);
  await page.locator('#history-table tr').first().click();await page.waitForSelector('#event-dialog[open]');
  const first=await id();
  assert.equal(await page.locator('#event-prev').isDisabled(),true,'primeiro não tem anterior');
  assert.match(await page.locator('#event-number').getAttribute('data-pos'),/^1 de 25$/);
  await page.click('#event-next');await page.waitForFunction(n=>!document.querySelector('#event-number').textContent.includes('#'+n),first);
  const second=await id();assert.notEqual(second,first);
  await page.keyboard.press('ArrowLeft');await page.waitForFunction(n=>document.querySelector('#event-number').textContent.includes('#'+n),first);
  // Passa da 20ª para a página seguinte.
  for(let i=0;i<20;i++){await page.keyboard.press('ArrowRight');await page.waitForTimeout(250);}
  assert.match(await page.locator('#event-number').getAttribute('data-pos'),/^21 de 25$/);
  assert.match(await page.locator('#page-indicator').innerText(),/21/);
  for(let i=0;i<4;i++){await page.keyboard.press('ArrowRight');await page.waitForTimeout(250);}
  assert.equal(await page.locator('#event-next').isDisabled(),true,'último não tem próximo');
  await page.keyboard.press('ArrowLeft');await page.waitForTimeout(400);
  assert.match(await page.locator('#event-number').getAttribute('data-pos'),/^24 de 25$/);
  await page.screenshot({path:'test-results/history-nav-pc.png'});
  await page.keyboard.press('Escape');
  // Celular: arrastar.
  const m=await (await browser.newContext({viewport:{width:390,height:844},hasTouch:true,isMobile:true})).newPage();
  await m.goto(base+'/#history');await m.waitForSelector('#history-table tr');
  await m.locator('#history-table tr').first().tap();await m.waitForSelector('#event-dialog[open]');
  const mid=async()=>Number((await m.locator('#event-number').innerText()).match(/#(\d+)/)[1]);
  const a=await mid();
  const swipe=async(dx)=>m.evaluate(async dx=>{const el=document.querySelector('#event-content');const mk=(type,x)=>{const t=new Touch({identifier:1,target:el,clientX:x,clientY:300});el.dispatchEvent(new TouchEvent(type,{bubbles:true,touches:type==='touchend'?[]:[t],changedTouches:[t]}));};mk('touchstart',200);mk('touchend',200+dx);},dx);
  await swipe(-150);await m.waitForFunction(n=>!document.querySelector('#event-number').textContent.includes('#'+n),a);
  const b=await mid();assert.notEqual(b,a);
  await swipe(150);await m.waitForFunction(n=>document.querySelector('#event-number').textContent.includes('#'+n),a);
  await m.screenshot({path:'test-results/history-nav-mobile.png'});
  assert.deepEqual(errors,[]);
  console.log('history nav ok');
} finally { await browser?.close(); server.kill(); }
