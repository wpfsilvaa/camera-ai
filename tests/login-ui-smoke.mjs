import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';

const data=await mkdtemp(path.join(tmpdir(),'casa-login-ui-'));
const shots=process.env.SCREENSHOTS;
const port=18051, base=`http://127.0.0.1:${port}`;
const server=spawn('.venv/bin/python',['tests/login_ui_server.py',String(port)],{env:{...process.env,PYTHONPATH:'.',CAMERA_DATA_DIR:data,WA_PORT:'18052',DASHBOARD_PASSWORD:''},stdio:['ignore','ignore','pipe']});
let logs='';server.stderr.on('data',chunk=>{logs+=chunk.toString();});
let browser;
try {
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
  for (let i=0;i<100;i++) { try { if ((await fetch(base+'/api/auth/me')).ok) break; } catch {} await new Promise(r=>setTimeout(r,200)); }
  const page=await browser.newPage({viewport:{width:1280,height:800}});
  page.on('dialog',dialog=>dialog.accept());
  // Without users the dashboard stays open locally and offers the first administrator.
  await page.goto(base+'/#users');
  await page.locator('#users-first').waitFor();
  assert.equal(await page.locator('#user-form [name=role]').isDisabled(),true);
  await page.fill('#user-form [name=name]','Waldemar');
  await page.fill('#user-form [name=username]','wal');
  await page.fill('#user-form [name=password]','senha-forte-1');
  await page.click('#user-form [type=submit]');
  await page.waitForURL(base+'/login');
  if (shots) await page.screenshot({path:`${shots}/login-desktop.png`});
  await page.fill('[name=username]','wal'); await page.fill('[name=password]','errada-000');
  await page.click('#login-submit');
  await page.locator('#login-error').waitFor();
  assert.match(await page.locator('#login-error').textContent(),/incorretos/);
  if (shots) await page.screenshot({path:`${shots}/login-error.png`});
  await page.fill('[name=password]','senha-forte-1'); await page.click('#login-submit');
  await page.waitForURL(base+'/');
  await page.locator('#account-name',{hasText:'Waldemar'}).waitFor();
  await page.goto(base+'/#users');
  await page.fill('#user-form [name=name]','Ana (irmã)');
  await page.fill('#user-form [name=username]','ana');
  await page.fill('#user-form [name=password]','familia-123');
  await page.click('#user-form [type=submit]');
  await page.locator('.user-row',{hasText:'Ana (irmã)'}).waitFor();
  if (shots) await page.screenshot({path:`${shots}/users.png`,fullPage:true});
  // Alerts: settings are saved, the test button explains a missing number and the overview lists alerts.
  await page.goto(base+'/#settings');
  await page.check('[name=alerts_enabled]');
  await page.fill('[name=inactivity_hours]','3');
  await page.selectOption('[name=daily_summary_hour]','20');
  await page.click('#save-settings');
  await page.locator('#toast',{hasText:'Configurações salvas'}).waitFor();
  const saved=await page.evaluate(()=>fetch('/api/settings').then(r=>r.json()));
  assert.equal(saved.alerts_enabled,true); assert.equal(saved.inactivity_hours,3); assert.equal(saved.daily_summary_hour,20);
  await page.click('#test-alert');
  await page.locator('#toast',{hasText:'Cadastre ao menos um número'}).waitFor();
  if (shots) await page.locator('#page-settings .settings-panel').last().screenshot({path:`${shots}/alerts-settings.png`});
  await page.fill('[name=recipient]','5511999999999'); await page.click('#save-settings');
  await page.locator('#toast',{hasText:'Configurações salvas'}).waitFor();
  await page.click('#test-alert');
  await page.goto(base+'/#overview');
  await page.locator('.alert-row',{hasText:'Teste de alerta'}).waitFor();
  if (shots) await page.locator('.alerts-panel').screenshot({path:`${shots}/alerts-overview.png`});
  await page.click('#account-button');
  if (shots) await page.screenshot({path:`${shots}/account.png`});
  await page.click('#logout-button');
  await page.waitForURL(base+'/login');

  // Family accounts see the dashboard without settings, users or the WhatsApp QR code.
  await page.fill('[name=username]','ana'); await page.fill('[name=password]','familia-123'); await page.click('#login-submit');
  await page.waitForURL(base+'/');
  await page.locator('#account-name',{hasText:'Ana'}).waitFor();
  assert.equal(await page.locator('[data-page=settings]').isVisible(),false);
  assert.equal(await page.locator('[data-page=users]').isVisible(),false);
  await page.goto(base+'/#settings');
  assert.equal(await page.locator('#page-settings').isVisible(),false);
  const status=await page.evaluate(()=>fetch('/api/status').then(r=>r.json()));
  assert.equal(status.whatsapp.qr,null);
  if (shots) await page.screenshot({path:`${shots}/family.png`});

  const phone=await browser.newPage({viewport:{width:390,height:844}});
  await phone.goto(base+'/login');
  assert.equal(await phone.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  if (shots) await phone.screenshot({path:`${shots}/login-phone.png`,fullPage:true});
  console.log('PASS: primeiro administrador, login, erro de senha, alertas, usuário família somente leitura, saída e tela móvel.');
} catch (error) {
  console.error(logs); throw error;
} finally {
  await browser?.close(); server.kill(); await rm(data,{recursive:true,force:true});
}
