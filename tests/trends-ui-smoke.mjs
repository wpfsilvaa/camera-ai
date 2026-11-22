// Tendências: gráficos de idas por parte do dia e de tempo na câmera, comparação das semanas, troca de período e tabela de números.
import {chromium} from 'playwright';
import {spawn,execFileSync} from 'node:child_process';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const data=await mkdtemp(path.join(tmpdir(),'trends-ui-'));
const base='http://127.0.0.1:18113';
const env={...process.env,PYTHONPATH:'.',CAMERA_DATA_DIR:data,DASHBOARD_PASSWORD:'',WA_PORT:'18114'};
execFileSync('.venv/bin/python',['-c',`
import time
from datetime import datetime, timedelta
from app.db import Database, TZ
from app.config import DATA
db=Database(DATA/'history.sqlite3')
father=db.rows("SELECT id FROM people WHERE is_father=1")[0]['id']
today=datetime.now(TZ).replace(hour=0,minute=0,second=0,microsecond=0)
for back in range(14):
    day=today-timedelta(days=back)
    for hour in ((2,3,9,15,20) if back<7 else (9,15)):
        t=(day+timedelta(hours=hour)).timestamp()
        if t>time.time(): continue
        db.execute("INSERT INTO restricted_visits(camera_id,started,area,kind) VALUES('main',?,'Geladeira','father')",(t,))
    start=(day+timedelta(hours=8)).timestamp()
    if start<time.time()-3600:
        event=db.start_event(start,1,camera_id='main',camera_name='Cozinha'); db.end_event(event,start+(back+2)*1800,'absence')
        db.execute("INSERT INTO person_tracks(event_id,track_key,started,last_seen,person_id) VALUES(?,?,?,?,?)",(event,'k',start,start,father))
`],{env});
const server=spawn('.venv/bin/python',['tests/manual_ui_server.py','18113'],{env,stdio:['ignore','ignore','pipe']});
let logs='',browser;server.stderr.on('data',c=>logs+=c);
try {
  for(let i=0;i<200;i++){try{if((await fetch(base+'/api/settings')).ok)break;}catch{}if(i===199)throw Error(logs);await new Promise(r=>setTimeout(r,200));}
  const api=await fetch(base+'/api/father/trends?days=14').then(r=>r.json());
  assert.equal(api.days.length,14);assert.ok(api.compare.visits.now>api.compare.visits.before,'a semana semeada tem mais idas');
  assert.equal((await fetch(base+'/api/father/trends?days=3')).status,422);
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
  for(const theme of ['light','dark']){
    const page=await browser.newPage({viewport:{width:1360,height:1000},colorScheme:theme});
    await page.goto(base+'/');await page.waitForSelector('#trend-visits svg');
    await page.locator('#trends-panel').scrollIntoViewIfNeeded();
    assert.equal(await page.locator('#trend-visits svg').getAttribute('role'),'img');
    assert.equal(await page.locator('#trend-visits svg text.axis.now').textContent(),'hoje');
    assert.ok(await page.locator('#trend-visits rect.bar.p-madrugada').count()>=3,'barras da madrugada');
    assert.ok(await page.locator('#trend-minutes rect.bar').count()>=5);
    const compare=await page.locator('#trend-compare').textContent();
    assert.match(compare,/idas à geladeira nos últimos 7 dias/);assert.match(compare,/de madrugada/);assert.match(compare,/na câmera/);assert.match(compare,/em relação à semana anterior/);
    assert.equal(await page.locator('#trend-rows tr').count(),14);
    // período
    await page.locator('[data-trend-days="30"]').click();
    await page.waitForFunction(()=>document.querySelectorAll('#trend-rows tr').length===30);
    await page.locator('[data-trend-days="7"]').click();
    await page.waitForFunction(()=>document.querySelectorAll('#trend-rows tr').length===7);
    assert.doesNotMatch(await page.locator('#trend-compare').textContent(),/semana anterior/,'com 7 dias não há com o que comparar');
    await page.locator('[data-trend-days="14"]').click();
    await page.waitForFunction(()=>document.querySelectorAll('#trend-rows tr').length===14);
    // cores diferentes por parte do dia (e legíveis nos dois temas)
    const fills=await page.evaluate(()=>['madrugada','manha','tarde','noite'].map(n=>getComputedStyle(document.querySelector(`#trend-legend i.p-${n}`)).backgroundColor));
    assert.equal(new Set(fills).size,4,'quatro cores distintas');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'rolagem lateral');
    await page.screenshot({path:`test-results/trends-${theme}.png`});
    await page.close();
  }
  const mobile=await browser.newPage({viewport:{width:390,height:844}});
  await mobile.goto(base+'/');await mobile.waitForSelector('#trend-visits svg');
  assert.equal(await mobile.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'rolagem lateral no celular');
  console.log('PASS: tendências: idas por parte do dia, tempo na câmera, comparação das semanas, períodos, tabela, tema claro/escuro e celular.');
} finally { await browser?.close(); server.kill(); }
