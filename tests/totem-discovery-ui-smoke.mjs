// Descoberta e pareamento de totem: o painel procura na rede, digita o código da tela do totem e passa a usá-lo.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const data=await mkdtemp(path.join(tmpdir(),'totem-ui-'));
const base='http://127.0.0.1:18095',totem='http://127.0.0.1:18096';
const env={...process.env,PYTHONPATH:'.',CAMERA_DATA_DIR:data,DASHBOARD_PASSWORD:'',WA_PORT:'18097',CASA_TOTEM_PORT:'18096',MONITOR_PORT:'18096',MONITOR_TOKEN_FILE:path.join(data,'totem-token'),MONITOR_PHOTOS_DIR:path.join(data,'p'),MONITOR_AVATARS_DIR:path.join(data,'a'),MONITOR_TTS_DIR:path.join(data,'t')};
const server=spawn('.venv/bin/python',['tests/history_nav_ui_server.py','18095'],{env,stdio:['ignore','ignore','pipe']});
const monitor=spawn('python3',['notebook/monitor.py'],{env,stdio:['ignore','pipe','pipe']});
let logs='',mlogs='',browser;server.stderr.on('data',c=>logs+=c);monitor.stderr.on('data',c=>mlogs+=c);monitor.stdout.on('data',c=>mlogs+=c);
try {
  for(let i=0;i<200;i++){try{if((await fetch(base+'/api/settings')).ok&&(await fetch(totem+'/hello')).ok)break;}catch{}if(i===199)throw Error(logs+mlogs);await new Promise(r=>setTimeout(r,200));}
  const code=(await (await fetch(totem+'/state')).json()).pairing.code;
  assert.match(code,/^\d{6}$/);
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1360,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/#settings');await page.waitForSelector('.settings-tab[data-group="totem"]');
  await page.click('.settings-tab[data-group="totem"]');await page.waitForSelector('#totem-scan',{state:'visible'});
  await page.click('#totem-scan');
  await page.waitForSelector('[data-pair="127.0.0.1"]',{timeout:30000});
  assert.match(await page.locator('#totem-list').innerText(),/Novo/);
  // Código errado: o totem recusa e continua sem token.
  await page.fill('[data-code="127.0.0.1"]',code==='000000'?'111111':'000000');await page.click('[data-pair="127.0.0.1"]');
  await page.waitForFunction(()=>document.querySelector('#toast')?.textContent.includes('incorreto'));
  assert.equal(await (await fetch(totem+'/hello')).json().then(j=>j.paired),false);
  // Código certo: pareia e o painel passa a usar este totem.
  await page.fill('[data-code="127.0.0.1"]',code);await page.click('[data-pair="127.0.0.1"]');
  await page.waitForSelector('#totem-list .pill.green',{timeout:30000});
  assert.match(await page.locator('#totem-list').innerText(),/Em uso/);
  assert.equal(await (await fetch(totem+'/hello')).json().then(j=>j.paired),true);
  const s=await (await fetch(base+'/api/settings')).json();
  assert.equal(s.notebook_url,totem);
  assert.equal(readFileSync(path.join(data,'notebook.token'),'utf8').trim(),readFileSync(path.join(data,'totem-token'),'utf8').trim());
  await page.screenshot({path:'test-results/totem-finder.png'});
  assert.deepEqual(errors,[]);
  console.log('totem discovery ok');
} finally { await browser?.close(); server.kill(); monitor.kill(); }
