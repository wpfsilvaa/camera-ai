import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';

await mkdir('test-results', { recursive: true });
const browser = await chromium.launch({executablePath:process.env.CHROME_PATH || '/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
try {
  const page = await browser.newPage({viewport:{width:1440,height:1050}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', msg => { if (msg.type()==='error' && !msg.text().includes('404')) errors.push(msg.text()); });
  await page.goto('http://127.0.0.1:8000');
  await page.waitForFunction(() => document.querySelector('#storage-info').textContent.includes('GB'));
  assert.equal(await page.locator('h1:visible').textContent(),'Um olhar sobre a rotina.');
  await page.screenshot({path:'test-results/dashboard-desktop.png',fullPage:true});
  await page.locator('a[data-page="settings"]').click();
  await page.locator('input[name="camera_name"]').waitFor({state:'visible'});
  assert.equal(await page.locator('input[name="camera_name"]').inputValue(),'Cozinha');
  assert.equal(await page.locator('input[name="father_only"]').isChecked(),true);
  await page.locator('#save-settings').click();
  await page.waitForFunction(() => document.querySelector('#toast').textContent==='Configurações salvas.');
  await page.locator('a[data-page="history"]').click();
  await page.locator('[data-filter="father"]').click();
  await page.locator('a[data-page="overview"]').click();
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'test-results/dashboard-mobile.png',fullPage:true});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false);
  assert.deepEqual(errors,[]);
  console.log('Dashboard: navegação, formulário, filtros e layout móvel OK.');
} finally { await browser.close(); }
