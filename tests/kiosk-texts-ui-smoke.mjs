// Configurações → Totem → Textos da tela: exemplo ao vivo, salvar, recarregar e restaurar os padrões.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const data=await mkdtemp(path.join(tmpdir(),'kiosk-texts-ui-'));
const base='http://127.0.0.1:18099';
const server=spawn('.venv/bin/python',['tests/manual_ui_server.py','18099'],{env:{...process.env,PYTHONPATH:'.',CAMERA_DATA_DIR:data,DASHBOARD_PASSWORD:'',WA_PORT:'18100'},stdio:['ignore','ignore','pipe']});
let logs='',browser;server.stderr.on('data',c=>logs+=c);
try {
  for(let i=0;i<200;i++){try{if((await fetch(base+'/api/settings')).ok)break;}catch{}if(i===199)throw Error(logs);await new Promise(r=>setTimeout(r,200));}
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1360,height:1000}});
  await page.goto(base+'/#settings');await page.waitForSelector('#settings-form [name=camera_source]');
  await page.locator('[role=tab][data-group=totem]').click();
  assert.equal(await page.locator('#kiosk-texts-panel').isVisible(),true);
  const morning=page.locator('[name=kiosk_text_greet_morning]'), rain=page.locator('[name=kiosk_text_daily_rain]');
  await morning.fill('Olá {nome}, hoje é {data} e são {hora}!');
  const preview=await morning.locator('xpath=..').locator('.text-preview').textContent();
  assert.match(preview,/^Exemplo: Olá Flavio, hoje é .* e são \d{2}:\d{2}!$/,preview);
  await page.locator('#kiosk-texts-panel summary:has-text("Resumo do dia")').click();
  await rain.fill('Chove {chuva}. [Dica: {sugestao}.]');
  assert.match(await rain.locator('xpath=..').locator('.text-preview').textContent(),/^Exemplo: Chove 70%\. Dica: leve o guarda-chuva/);
  await page.locator('[name=kiosk_tips_enabled]').click();   // desliga as sugestões
  await page.waitForFunction(()=>/Exemplo: Chove 70%\.$/.test(document.querySelector('[name=kiosk_text_daily_rain]').parentElement.querySelector('.text-preview').textContent));
  await page.locator('#save-settings').click();
  await page.waitForSelector('.toast');
  const saved=await fetch(base+'/api/settings').then(r=>r.json());
  assert.equal(saved.kiosk_text_greet_morning,'Olá {nome}, hoje é {data} e são {hora}!');
  assert.equal(saved.kiosk_tips_enabled,false);
  await page.reload();await page.waitForSelector('#settings-form [name=camera_source]',{state:'attached'});
  await page.locator('[role=tab][data-group=totem]').click();
  assert.equal(await page.locator('[name=kiosk_text_greet_morning]').inputValue(),'Olá {nome}, hoje é {data} e são {hora}!');
  await page.locator('#kiosk-texts-reset').click();
  assert.equal(await page.locator('[name=kiosk_text_greet_morning]').inputValue(),'');
  await page.waitForTimeout(300);
  await page.locator('#save-settings').click();
  await page.waitForFunction(async()=>(await (await fetch('/api/settings')).json()).kiosk_text_greet_morning==='');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'rolagem lateral');
  await page.screenshot({path:'test-results/kiosk-texts-panel.png'});
  console.log('PASS: textos da tela com exemplo ao vivo, salvar, recarregar e restaurar.');
} finally { await browser?.close(); server.kill(); }
