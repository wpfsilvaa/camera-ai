import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp,mkdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const data=await mkdtemp(path.join(tmpdir(),'recipients-ui-'));
const base='http://127.0.0.1:18031';
const server=spawn('.venv/bin/python',['tests/recipients_ui_server.py','18031'],{env:{...process.env,PYTHONPATH:'.',CAMERA_DATA_DIR:data,DASHBOARD_PASSWORD:'',WA_PORT:'18032'},stdio:['ignore','ignore','pipe']});
let logs='',browser;server.stderr.on('data',c=>logs+=c);
try {
 for(let i=0;i<100;i++){
  try{if((await fetch(base+'/api/settings')).ok)break;}catch{}
  if(i===99)throw Error(logs);
  await new Promise(r=>setTimeout(r,200));
 }
 browser=await chromium.launch({executablePath:'/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1360,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('dialog',dialog=>dialog.accept());
 await page.goto(base+'/#settings');
 const family=page.locator('[name=additional_recipients]');
 await family.waitFor();
 assert.equal(await family.inputValue(),'5511888888888');
 await family.fill('+55 (11) 88888-8888\n55 11 77777-7777\n5511888888888');
 await page.locator('#save-settings').click();
 await page.waitForFunction(()=>document.querySelector('[name=additional_recipients]').value==='5511888888888\n5511777777777');
 await page.reload();
 await page.waitForFunction(()=>document.querySelector('[name=additional_recipients]').value==='5511888888888\n5511777777777');
 assert.equal(await page.locator('[name=recipient]').inputValue(),'5511999999999');
 await page.setViewportSize({width:390,height:844});
 await mkdir('test-results',{recursive:true});
 await page.screenshot({path:'test-results/recipients-mobile.png',fullPage:true});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
 await page.locator('a[data-page=history]').click();
 await page.locator('#history-table [data-event="1"]').click();
 await page.locator('.recipient-delivery').first().waitFor();
 assert.equal(await page.locator('.recipient-delivery').count(),2);
 assert.equal(await page.locator('[data-retry]').count(),1);
 await page.locator('[data-recipient="5511888888888"]').click();
 await page.waitForFunction(()=>document.querySelectorAll('[data-retry]').length===0);
 const calls=await (await fetch(base+'/test-requests')).json();
 assert.deepEqual(calls,[{path:'/retry',payload:{clip_id:'a'.repeat(32),recipient:'5511888888888'}}]);
 const event=await (await fetch(base+'/api/events/1')).json();
 assert.equal(event.clips[0].deliveries.find(d=>d.recipient==='5511999999999').delivery,'sent');
 assert.equal(event.clips[0].deliveries.find(d=>d.recipient==='5511888888888').delivery,'pending');
 await page.screenshot({path:'test-results/recipients-history-mobile.png',fullPage:true});
 assert.deepEqual(errors,[]);
 console.log('Destinatários: formulário, normalização, persistência, tela móvel, histórico por número e reenvio seletivo validados. Nenhum envio real.');
}finally{
 await browser?.close();server.kill('SIGTERM');
 await new Promise(resolve=>{server.once('exit',resolve);setTimeout(()=>{server.kill('SIGKILL');resolve();},5000).unref();});
 await rm(data,{recursive:true,force:true});
}
