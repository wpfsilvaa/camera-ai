import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { mkdtemp, mkdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { once } from 'node:events';
import path from 'node:path';
import assert from 'node:assert/strict';

const data=await mkdtemp(path.join(tmpdir(),'casa-people-ui-'));
const port=18011, base=`http://127.0.0.1:${port}`;
const server=spawn('.venv/bin/python',['tests/people_ui_server.py',String(port)],{env:{...process.env,PYTHONPATH:'.',CAMERA_DATA_DIR:data,WA_PORT:'18012',DASHBOARD_PASSWORD:''},stdio:['ignore','ignore','pipe']});
let logs='';server.stderr.on('data',chunk=>{logs+=chunk.toString();});
let browser;
try {
  let ready=false;
  for(let i=0;i<50;i++) {
    try {if((await fetch(base+'/api/settings')).ok){ready=true;break;}} catch {}
    await new Promise(resolve=>setTimeout(resolve,200));
  }
  assert.ok(ready,logs);
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1360,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/#people');
  await page.locator('.profile-card').waitFor();
  await page.locator('#person-name').fill('Maria');
  await page.locator('#person-form button').click();
  await page.waitForFunction(()=>document.querySelectorAll('.profile-card').length===2);
  const profiles=await (await fetch(base+'/api/people')).json();
  const maria=profiles.profiles.find(p=>p.name==='Maria').id;
  await page.locator('[data-face-upload="father"]').click();
  assert.equal(await page.locator('#face-dialog').isVisible(),true);
  const chooserPromise=page.waitForEvent('filechooser');
  await page.locator('#face-choose').click();
  const chooser=await chooserPromise;
  // The real file chooser may stay open through multiple dashboard refreshes.
  await page.waitForTimeout(6500);
  await chooser.setFiles('tests/assets/lena.jpg');
  await page.locator('#face-editor:not(.hidden)').waitFor();
  await page.waitForTimeout(3200);
  let before=await (await fetch(base+'/api/people')).json();
  assert.equal(before.profiles.find(p=>p.id==='father').enrollments.length,0,'Selection alone must not upload');
  const area=await page.locator('#face-canvas').boundingBox();
  const crop=async(x1,y1,x2,y2)=>{
    await page.mouse.move(area.x+area.width*x1,area.y+area.height*y1);
    await page.mouse.down();
    await page.mouse.move(area.x+area.width*x2,area.y+area.height*y2,{steps:8});
    await page.mouse.up();
  };
  await crop(.01,.01,.3,.3); // No face: backend error must stay in the dialog.
  await page.locator('#face-save').click();
  await page.locator('#face-error:not(.hidden)').waitFor();
  assert.equal(await page.locator('#face-dialog').isVisible(),true);
  await crop(.3,.28,.88,.92);
  await mkdir('test-results',{recursive:true});
  await page.screenshot({path:'test-results/face-crop.png',fullPage:true});
  await page.locator('#face-save').click();
  await page.waitForFunction(()=>!document.querySelector('#face-dialog').open);

  await page.waitForFunction(()=>document.querySelectorAll('.enrollment-photos img').length===1);
  const enrolled=await (await fetch(base+'/api/people')).json();
  assert.equal(enrolled.profiles.find(p=>p.id==='father').enrollments.length,1);
  const invalid=await fetch(base+'/api/people/father/faces',{method:'POST',headers:{'X-Casa-Request':'1'},body:'invalid photo'});
  assert.equal(invalid.status,422);
  await page.locator('a[data-page="history"]').click();
  await page.locator('#history-table [data-event="1"]').click();
  await page.locator('[data-track-person="1"]').selectOption('father');
  await page.locator('[data-confirm-track="1"]').click();
  await page.waitForFunction(()=>document.querySelector('[data-track="1"] .pill')?.textContent==='Meu pai');
  await page.locator('[data-track-person="2"]').selectOption(maria);
  await page.locator('[data-confirm-track="2"]').click();
  await page.waitForFunction(()=>document.querySelector('[data-track="2"] .pill')?.textContent==='Maria');
  const record=await (await fetch(base+'/api/events/1')).json();
  assert.equal(record.people.length,2);
  assert.equal(record.identity,'father');
  assert.equal(record.people[0].samples[0].person_id,'father');
  assert.equal(record.people[1].samples[0].person_id,maria);
  await mkdir('test-results',{recursive:true});
  await page.screenshot({path:'test-results/people-review.png',fullPage:true});
  await page.locator('#event-dialog .close-dialog').click();
  await page.locator('a[data-page="people"]').click();
  await page.screenshot({path:'test-results/people-profiles.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.locator('[data-face-upload="father"]').click();
  await page.locator('#face-file').setInputFiles('tests/assets/lena.jpg');
  await page.locator('#face-editor:not(.hidden)').waitFor();
  assert.equal(await page.evaluate(()=>{const r=document.querySelector('#face-dialog').getBoundingClientRect();return r.left>=0 && r.right<=innerWidth;}),true);
  await page.screenshot({path:'test-results/face-crop-mobile.png',fullPage:true});
  await page.locator('#face-cancel').click();
  const afterCancel=await (await fetch(base+'/api/people')).json();
  assert.equal(afterCancel.profiles.find(p=>p.id==='father').enrollments.length,1);
  await page.locator('[data-review-examples="father"]').click();
  await page.waitForFunction(()=>document.querySelectorAll('.example-card').length===2);
  await page.waitForTimeout(3200); // Periodic profile refresh must not close or rebuild this dialog.
  await page.locator('#examples-sort').selectOption('quality');
  assert.equal(await page.locator('[data-delete-example]').first().getAttribute('data-source'),'history');
  await page.locator('[data-view-example][data-source="history"]').click();
  await page.locator('#example-photo-dialog').waitFor();
  await page.waitForFunction(()=>{const image=document.querySelector('#example-photo');return image.complete && image.naturalWidth>0;});
  await page.locator('#example-photo-close').click();
  await page.screenshot({path:'test-results/examples-mobile.png',fullPage:true});
  await page.locator('[data-delete-example][data-source="history"]').click();
  await page.waitForFunction(()=>document.querySelectorAll('.example-card').length===1);
  const preserved=await (await fetch(base+'/api/events/1')).json();
  assert.equal(preserved.identity,'father');
  assert.equal(preserved.people[0].person_id,'father');
  assert.equal(preserved.people[0].samples[0].person_id,null);
  assert.equal(preserved.people[1].samples[0].person_id,maria);
  const remaining=await (await fetch(base+'/api/people/father/examples')).json();
  assert.equal(remaining.examples.length,1);
  await page.locator('#examples-source').selectOption('history');
  assert.equal(await page.locator('.example-card').count(),0);
  await page.locator('#examples-source').selectOption('upload');
  await page.locator('[data-delete-example][data-source="upload"]').click();
  await page.waitForFunction(()=>document.querySelectorAll('.example-card').length===0);
  assert.ok((await page.locator('#examples-count').textContent()).startsWith('0 exemplo'));
  await page.locator('#examples-close').click();
  page.on('dialog',dialog=>dialog.accept());
  await page.locator('[data-forget-person="father"]').click();
  await page.waitForFunction(()=>document.querySelector('.profile-card p').textContent.startsWith('0 rosto'));
  await page.locator(`[data-delete-person="${maria}"]`).click();
  await page.waitForFunction(()=>document.querySelectorAll('.profile-card').length===1);
  await page.locator('a[data-page="overview"]').click();
  await page.waitForFunction(()=>document.querySelector('#live-image').naturalWidth===960);
  const frameHash=()=>page.evaluate(()=>{const img=document.querySelector('#live-image');const canvas=document.createElement('canvas');canvas.width=img.naturalWidth;canvas.height=img.naturalHeight;canvas.getContext('2d').drawImage(img,0,0);return canvas.toDataURL();});
  const first=await frameHash();
  await page.waitForTimeout(300);
  assert.notEqual(await frameHash(),first,'MJPEG must advance in the browser');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:'test-results/mobile-stream.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('Interface validada: cadastro, duas pessoas no mesmo registro, ensino, esquecimento, exclusão e layout móvel. Dados temporários; nenhum envio.');
} finally {
  await browser?.close();
  if(server.exitCode===null){server.kill('SIGTERM');await once(server,'exit');}
  await rm(data,{recursive:true,force:true});
}
