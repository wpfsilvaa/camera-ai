// Assistente de primeira configuração numa instalação nova: relação, câmera, aviso e administrador.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const data=await mkdtemp(path.join(tmpdir(),'setup-ui-'));
const base='http://127.0.0.1:18093';
const server=spawn('.venv/bin/python',['tests/history_nav_ui_server.py','18093'],{env:{...process.env,PYTHONPATH:'.',CAMERA_DATA_DIR:data,DASHBOARD_PASSWORD:'',WA_PORT:'18094'},stdio:['ignore','ignore','pipe']});
let logs='',browser;server.stderr.on('data',c=>logs+=c);
try {
  for(let i=0;i<200;i++){try{if((await fetch(base+'/api/settings')).ok)break;}catch{}if(i===199)throw Error(logs);await new Promise(r=>setTimeout(r,200));}
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1360,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/');
  await page.waitForSelector('#setup-banner:not(.hidden)',{timeout:8000});
  await page.click('#setup-start');await page.waitForSelector('#setup-dialog[open]');
  assert.match(await page.locator('#setup-step-label').innerText(),/PASSO 1 DE 4/);
  await page.selectOption('#setup-relation','mãe');await page.click('#setup-next');
  await page.waitForSelector('[data-step="2"]:not(.hidden)');
  await page.click('#setup-next');   // sem endereço: pede o endereço
  assert.match(await page.locator('#setup-error').innerText(),/endereço da câmera/);
  await page.fill('#setup-camera-source','rtsp://127.0.0.1:9/nada');await page.click('#setup-next');
  await page.waitForSelector('[data-step="3"]:not(.hidden)');
  await page.click('#setup-skip');await page.waitForSelector('[data-step="4"]:not(.hidden)');
  await page.click('#setup-next');
  assert.match(await page.locator('#setup-error').innerText(),/8 caracteres/);
  await page.fill('#setup-admin-name','Ana');await page.fill('#setup-admin-user','ana');await page.fill('#setup-admin-pass','senha-forte-123');
  await page.screenshot({path:'test-results/setup-wizard.png'});
  await page.click('#setup-next');await page.waitForURL('**/login**');
  // Depois do login, a configuração ficou salva e o assistente não volta.
  const login=await page.request.post(base+'/api/auth/login',{headers:{'Content-Type':'application/json','X-Casa-Request':'1'},data:{username:'ana',password:'senha-forte-123'}});
  assert.equal(login.status(),200);
  const s=await (await page.request.get(base+'/api/settings')).json();
  assert.equal(s.elder_relation,'mãe');assert.equal(s.setup_done,true);assert.equal(s.camera_source,'rtsp://127.0.0.1:9/nada');
  await page.goto(base+'/');await page.waitForTimeout(2500);
  assert.equal(await page.locator('#setup-banner').isVisible(),false);
  assert.deepEqual(errors.filter(e=>!/login/i.test(e)),[]);
  console.log('setup ui ok');
} finally { await browser?.close(); server.kill(); }
