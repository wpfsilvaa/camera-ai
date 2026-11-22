// Revisão de idas à geladeira: "Foi <pai>", "Foi outra pessoa…" (lista dos cadastrados) e "Não foi", com o veredito gravado.
import {chromium} from 'playwright';
import {spawn,execFileSync} from 'node:child_process';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const data=await mkdtemp(path.join(tmpdir(),'visit-review-ui-'));
const base='http://127.0.0.1:18089';
const env={...process.env,PYTHONPATH:'.',CAMERA_DATA_DIR:data,DASHBOARD_PASSWORD:'',WA_PORT:'18090'};
execFileSync('.venv/bin/python',['-c',`
import time
from app.db import Database
from app.config import DATA
db=Database(DATA/'history.sqlite3')
db.execute("INSERT INTO people(id,name,created,is_father) VALUES('lorena','Lorena',2,0)")
now=time.time()
for i in range(3):
    db.execute("INSERT INTO restricted_visits(camera_id,started,area,kind) VALUES('main',?,'Geladeira','unknown')",(now-60*(i+1),))
`],{env});
const server=spawn('.venv/bin/python',['tests/manual_ui_server.py','18089'],{env,stdio:['ignore','ignore','pipe']});
let logs='',browser;server.stderr.on('data',c=>logs+=c);
const visits=()=>fetch(base+'/api/father/visits').then(r=>r.json());
try {
  for(let i=0;i<200;i++){try{if((await fetch(base+'/api/settings')).ok)break;}catch{}if(i===199)throw Error(logs);await new Promise(r=>setTimeout(r,200));}
  assert.equal((await visits()).length,3);
  const father=(await fetch(base+'/api/people').then(r=>r.json())).profiles.find(p=>p.is_father);
  assert.ok(father,'o servidor de teste deveria ter uma pessoa monitorada');
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1360,height:900}});
  await page.goto(base+'/');
  await page.waitForSelector('#review-visits',{state:'attached'});
  await page.evaluate(()=>document.querySelector('#review-visits').click());
  await page.waitForSelector('#visits-list [data-visit]');
  const card=page.locator('#visits-list [data-visit]').first();
  assert.equal((await card.locator('[data-verdict=father]').textContent()).trim(),`Foi ${father.name.split(' ')[0]}`);
  assert.deepEqual(await card.locator('[data-who] option').allTextContents(),['Foi outra pessoa…','Lorena']);
  await card.locator('[data-verdict=father]').click();
  await page.waitForFunction(()=>document.querySelectorAll('#visits-list [data-visit]').length===2);
  await page.locator('#visits-list [data-visit]').first().locator('[data-who]').selectOption('lorena');
  await page.waitForFunction(()=>document.querySelectorAll('#visits-list [data-visit]').length===1);
  await page.locator('#visits-list [data-visit] [data-verdict=other]').click();
  await page.waitForFunction(()=>document.querySelectorAll('#visits-list [data-visit]').length===0);
  const rows=execFileSync('.venv/bin/python',['-c',`
from app.db import Database
from app.config import DATA
print([(r['verdict'],r['person_id']) for r in Database(DATA/'history.sqlite3').rows('SELECT verdict,person_id FROM restricted_visits ORDER BY started DESC')])`],{env}).toString().trim();
  assert.equal(rows,`[('father', '${father.id}'), ('other', 'lorena'), ('other', None)]`,rows);
  await page.screenshot({path:'test-results/visit-review.png'});
  console.log('PASS: revisão de idas com "Foi ele", "Foi outra pessoa…" e "Não foi".');
} finally { await browser?.close(); server.kill(); }
