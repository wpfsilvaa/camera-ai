// Alertas: painel "Idas à geladeira fora do padrão" (salvar e recarregar). Totem: botão de reiniciar a tela com confirmação em dois toques.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const data=await mkdtemp(path.join(tmpdir(),'fridge-restart-ui-'));
const base='http://127.0.0.1:18101';
const server=spawn('.venv/bin/python',['tests/manual_ui_server.py','18101'],{env:{...process.env,PYTHONPATH:'.',CAMERA_DATA_DIR:data,DASHBOARD_PASSWORD:'',WA_PORT:'18102'},stdio:['ignore','ignore','pipe']});
let logs='',browser;server.stderr.on('data',c=>logs+=c);
try {
  for(let i=0;i<200;i++){try{if((await fetch(base+'/api/settings')).ok)break;}catch{}if(i===199)throw Error(logs);await new Promise(r=>setTimeout(r,200));}
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1360,height:1000}});
  const restarts=[];
  await page.route('**/api/kiosk/restart',r=>{restarts.push(r.request().method());r.fulfill({contentType:'application/json',body:'{"ok":true}'});});
  await page.goto(base+'/#settings');await page.waitForSelector('#settings-form [name=camera_source]',{state:'attached'});
  // alertas
  await page.evaluate(()=>document.querySelector('[role=tab][data-group=alerts]').click());
  assert.equal(await page.locator('#fridge-panel').isVisible(),true);
  await page.locator('[name=fridge_alerts_enabled]').click();
  await page.locator('[name=fridge_night_visits]').fill('4');
  await page.locator('[name=fridge_night_start_hour]').selectOption('23');
  await page.locator('[name=fridge_night_end_hour]').selectOption('5');
  await page.locator('[name=fridge_daily_visits]').fill('10');
  await page.locator('#save-settings').click();await page.waitForSelector('.toast');
  const saved=await fetch(base+'/api/settings').then(r=>r.json());
  assert.deepEqual([saved.fridge_alerts_enabled,saved.fridge_night_visits,saved.fridge_night_start_hour,saved.fridge_night_end_hour,saved.fridge_daily_visits],[true,4,23,5,10]);
  await page.screenshot({path:'test-results/fridge-panel.png'});
  // totem: dois toques
  await page.evaluate(()=>document.querySelector('[role=tab][data-group=totem]').click());
  const button=page.locator('#kiosk-restart');
  await button.scrollIntoViewIfNeeded();
  await button.click();
  assert.match(await button.textContent(),/confirmar/i);
  assert.deepEqual(restarts,[],'o primeiro toque não deve reiniciar');
  await button.click();
  await page.waitForFunction(()=>document.querySelector('#kiosk-restart').textContent.trim()==='Reiniciar a tela');
  await page.waitForTimeout(300);
  assert.deepEqual(restarts,['POST']);
  // sem segundo toque, volta ao normal sozinho
  await button.click();await page.waitForTimeout(4400);
  assert.equal((await button.textContent()).trim(),'Reiniciar a tela');
  assert.deepEqual(restarts,['POST']);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'rolagem lateral');
  console.log('PASS: painel de idas à geladeira salva; reiniciar a tela pede confirmação e chama a rota uma vez.');
} finally { await browser?.close(); server.kill(); }
