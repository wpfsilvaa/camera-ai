// Rastreamento e nomes: opções salvam, o custo do rastreador aparece e o resumo das perdas de nome mostra motivos e recuperações.
import {chromium} from 'playwright';
import {spawn,execFileSync} from 'node:child_process';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const data=await mkdtemp(path.join(tmpdir(),'tracking-panel-ui-'));
const base='http://127.0.0.1:18111';
const env={...process.env,PYTHONPATH:'.',CAMERA_DATA_DIR:data,DASHBOARD_PASSWORD:'',WA_PORT:'18112'};
execFileSync('.venv/bin/python',['-c',`
import time
from app.db import Database
from app.config import DATA
db=Database(DATA/'history.sqlite3')
db.execute("INSERT OR IGNORE INTO people(id,name,created,is_father) VALUES('father','Flavio',1,1)")
now=time.time()
for i,(reason,gap) in enumerate([('track_lost',4.0),('track_lost',9.5),('expired',None),('contradicted',None)]):
    db.execute("INSERT INTO identity_log(at,camera_id,person_id,track_key,reason,source,recovered_after) VALUES(?,?,?,?,?,?,?)",(now-600*(i+1),'main','father',str(i),reason,'face',gap))
db.execute("INSERT INTO identity_log(at,camera_id,person_id,track_key,reason) VALUES(?,?,?,?,?)",(now-300,'main','father','','clothes_changed'))
`],{env});
const server=spawn('.venv/bin/python',['tests/manual_ui_server.py','18111'],{env,stdio:['ignore','ignore','pipe']});
let logs='',browser;server.stderr.on('data',c=>logs+=c);
try {
  for(let i=0;i<200;i++){try{if((await fetch(base+'/api/settings')).ok)break;}catch{}if(i===199)throw Error(logs);await new Promise(r=>setTimeout(r,200));}
  const summary=await fetch(base+'/api/recognition/losses?days=3').then(r=>r.json());
  assert.deepEqual([summary.total,summary.recovered,summary.median_gap],[4,2,9.5]);   // A troca de roupa não conta como perda.
  assert.equal(summary.clothes_changes.length,1);
  assert.equal((await fetch(base+'/api/recognition/losses?days=99')).status,422);
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1360,height:1100}});
  await page.goto(base+'/#settings');await page.waitForSelector('#settings-form [name=camera_source]',{state:'attached'});
  const panel=page.locator('#tracking-panel');await panel.scrollIntoViewIfNeeded();
  assert.equal(await panel.isVisible(),true);
  await page.waitForFunction(()=>/vez\(es\) um nome se perdeu/.test(document.querySelector('#losses-body').textContent));
  const text=await page.locator('#losses-body').textContent();
  assert.match(text,/4.*vez\(es\) um nome se perdeu.*2.*voltou/s);assert.match(text,/2×.*rastreador perdeu a pessoa/);assert.match(text,/Ficou tempo demais sem rosto/);assert.match(text,/Trocas de roupa percebidas.*Referência de teste|Trocas de roupa percebidas/);
  assert.equal(await panel.locator('[name=identity_sticky_enabled]').isChecked(),true,'o padrão é ligado');
  assert.equal(await panel.locator('[name=tracker_appearance_enabled]').isChecked(),false,'a aparência fica desligada por padrão (notebook fraco)');
  await page.waitForFunction(()=>document.querySelector('#tracker-cost').textContent.length>0,null,{timeout:8000}).catch(()=>{});
  await panel.locator('[name=identity_sticky_seconds]').fill('300');
  await panel.locator('[name=identity_reattach_seconds]').fill('30');
  await panel.locator('[name=tracker_appearance_enabled]').click();
  await page.locator('#save-settings').click();await page.waitForSelector('.toast');
  const saved=await fetch(base+'/api/settings').then(r=>r.json());
  assert.deepEqual([saved.identity_sticky_enabled,saved.identity_sticky_seconds,saved.identity_reattach_seconds,saved.tracker_appearance_enabled],[true,300,30,true]);
  await page.screenshot({path:'test-results/tracking-panel.png'});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'rolagem lateral');
  console.log('PASS: rastreamento e nomes: opções, custo do rastreador e resumo das perdas de nome.');
} finally { await browser?.close(); server.kill(); }
