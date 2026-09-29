import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp,mkdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {once} from 'node:events';
import path from 'node:path';
import assert from 'node:assert/strict';
const data=await mkdtemp(path.join(tmpdir(),'manual-ui-'));
const base='http://127.0.0.1:18021';
const server=spawn('.venv/bin/python',['tests/manual_ui_server.py','18021'],{env:{...process.env,PYTHONPATH:'.',CAMERA_DATA_DIR:data,DASHBOARD_PASSWORD:'',WA_PORT:'18022'},stdio:['ignore','ignore','pipe']});
let logs='',browser;server.stderr.on('data',c=>logs+=c);
try {
  for(let i=0;i<180;i++) {
    try{if((await fetch(base+'/api/settings')).ok)break;}catch{}
    if(i===179)throw Error(logs);
    await new Promise(r=>setTimeout(r,200));
  }
  browser=await chromium.launch({executablePath:'/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1360,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);
  await page.waitForFunction(()=>document.querySelector('#live-image').naturalWidth===1280);
  assert.equal(await page.locator('#toggle-analysis').textContent(),'Retomar análise');
  const hash=()=>page.evaluate(()=>{const image=document.querySelector('#live-image'),c=document.createElement('canvas');c.width=10;c.height=10;c.getContext('2d').drawImage(image,0,0,10,10);return image.naturalWidth;});
  assert.equal(await hash(),1280);
  await page.locator('#fullscreen-camera').click();
  await page.waitForFunction(()=>!!document.fullscreenElement);
  await page.evaluate(()=>document.exitFullscreen());
  await page.locator('#toggle-recording').click();
  await page.waitForFunction(()=>document.querySelector('#toggle-recording').textContent==='Parar gravação manual');
  await page.waitForTimeout(2300);
  await page.locator('#toggle-recording').click();
  await page.waitForFunction(()=>document.querySelector('#toggle-recording').textContent==='Gravar manualmente');
  await page.locator('a[data-page="history"]').click();
  await page.locator('#history-table [data-event="1"]').click();
  for(let i=0;i<30 && await page.locator('[data-analyze-event]').isDisabled();i++){
    await page.waitForTimeout(300);await page.locator('[data-refresh-event]').click();
  }
  await page.locator('[data-analyze-event="1"]').click();
  await page.waitForFunction(()=>document.querySelector('#event-content .manual-analysis strong')?.textContent==='Vídeo analisado',null,{timeout:45000});
  assert.ok((await page.locator('.event-video').getAttribute('src')).endsWith('.analyzed.mp4'));
  assert.ok(await page.locator('.person-track').count()>0);
  assert.ok((await page.locator('.person-track').first().textContent()).includes('Referência de teste'));
  const event=await (await fetch(base+'/api/events/1')).json();
  assert.equal(event.kind,'manual');assert.equal(event.analysis_state,'complete');
  assert.equal((await fetch(base+`/media/${event.clips[0].id}.mp4`)).status,200);
  await mkdir('test-results',{recursive:true});
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'test-results/manual-analysis-mobile.png',fullPage:true});
  await page.locator('#event-dialog .close-dialog').click();
  await page.locator('a[data-page="overview"]').click();
  await page.locator('#toggle-analysis').click();
  await page.waitForFunction(()=>document.querySelector('#toggle-analysis').textContent==='Pausar análise');
  await page.waitForTimeout(1500);
  await page.locator('#toggle-analysis').click();
  await page.waitForFunction(()=>document.querySelector('#toggle-analysis').textContent==='Retomar análise');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  assert.deepEqual(errors,[]);
  console.log('Painel validado: preview pausado, tela cheia, gravação manual, análise posterior, vídeo identificado e retomada/pausa. Nenhum envio.');
} finally {
  await browser?.close();
  if(server.exitCode===null){server.kill('SIGTERM');await once(server,'exit');}
  await rm(data,{recursive:true,force:true});
}
