// Menu por papel e aparelho (celular: barra com "Mais"; computador: grupos), nos dois temas, sem rolagem lateral.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const data=await mkdtemp(path.join(tmpdir(),'menu-ui-'));
const base='http://127.0.0.1:18083';
const server=spawn('.venv/bin/python',['tests/manual_ui_server.py','18083'],{env:{...process.env,PYTHONPATH:'.',CAMERA_DATA_DIR:data,DASHBOARD_PASSWORD:'',WA_PORT:'18084'},stdio:['ignore','ignore','pipe']});
let logs='',browser;server.stderr.on('data',c=>logs+=c);
try {
  for(let i=0;i<200;i++){try{if((await fetch(base+'/api/settings')).ok)break;}catch{}if(i===199)throw Error(logs);await new Promise(r=>setTimeout(r,200));}
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
  const visible=(page,sel)=>page.locator(sel).evaluateAll(els=>els.filter(e=>e.offsetParent!==null).map(e=>e.dataset.page||e.dataset.sheet||e.id));
  for(const theme of ['light','dark']) for(const family of [false,true]) {
    // celular
    let page=await browser.newPage({viewport:{width:390,height:844},colorScheme:theme});
    await page.goto(base+'/');await page.waitForTimeout(800);
    if(family) await page.evaluate(()=>document.body.classList.add('readonly'));
    const bar=await visible(page,'.sidebar .nav-link');
    assert.deepEqual(bar,['overview','history','messages','health','nav-more'],`${theme} family=${family} barra: ${bar}`);
    await page.click('#nav-more');
    const sheet=await visible(page,'#more-sheet .more-link');
    assert.deepEqual(sheet,family?['people']:['people','settings','users'],`folha: ${sheet}`);
    await page.click('#more-sheet .more-link[data-sheet=people]');await page.waitForTimeout(300);
    assert.equal(await page.locator('#more-sheet').evaluate(e=>e.classList.contains('hidden')),true);
    assert.equal(await page.locator('#nav-more').evaluate(e=>e.classList.contains('active')),true);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'rolagem lateral no celular');
    await page.screenshot({path:`test-results/menu-mobile-${theme}-${family?'familia':'admin'}.png`});
    await page.close();
    // computador
    page=await browser.newPage({viewport:{width:1360,height:900},colorScheme:theme});
    await page.goto(base+'/');await page.waitForTimeout(800);
    if(family) await page.evaluate(()=>document.body.classList.add('readonly'));
    const side=await visible(page,'.sidebar .nav-link:not(.nav-more)');
    assert.deepEqual(side,family?['overview','history','messages','people','health']:['overview','history','messages','people','health','settings','users'],`menu pc: ${side}`);
    const labels=await page.locator('.nav-group .nav-label').evaluateAll(els=>els.filter(e=>e.offsetParent!==null).map(e=>e.textContent));
    assert.deepEqual(labels,family?['ACOMPANHAR','CUIDAR']:['ACOMPANHAR','CUIDAR','ADMINISTRAR']);
    assert.equal(await page.locator('#nav-more').isVisible(),false);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'rolagem lateral no pc');
    await page.screenshot({path:`test-results/menu-pc-${theme}-${family?'familia':'admin'}.png`});
    await page.close();
  }
  console.log('menu ui ok');
} finally { await browser?.close(); server.kill(); }
