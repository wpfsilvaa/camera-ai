// A relação da pessoa acompanhada muda os textos (gênero), sem mexer no que as pessoas digitam.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const data=await mkdtemp(path.join(tmpdir(),'elder-ui-'));
const base='http://127.0.0.1:18089';
const server=spawn('.venv/bin/python',['tests/history_nav_ui_server.py','18089'],{env:{...process.env,PYTHONPATH:'.',CAMERA_DATA_DIR:data,DASHBOARD_PASSWORD:'',WA_PORT:'18090'},stdio:['ignore','ignore','pipe']});
let logs='',browser;server.stderr.on('data',c=>logs+=c);
try {
  for(let i=0;i<200;i++){try{if((await fetch(base+'/api/settings')).ok)break;}catch{}if(i===199)throw Error(logs);await new Promise(r=>setTimeout(r,200));}
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1360,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/');await page.waitForSelector('#page-overview');await page.waitForTimeout(800);
  assert.match(await page.locator('.workspace').innerText(),/Casa do meu pai/);
  // Conversão direta (regras de gênero).
  const c=await page.evaluate(()=>{window.setElderRelation('mãe');return ['Acompanhe a presença do seu pai','Casa do meu pai','Registros do pai','O pai hoje','Foi ele','Lembrar o pai','Te amo, pai'].map(window.elderConvert)});
  assert.deepEqual(c,['Acompanhe a presença da sua mãe','Casa da minha mãe','Registros da mãe','A mãe hoje','Foi ela','Lembrar a mãe','Te amo, mãe']);
  assert.match(await page.locator('.workspace').innerText(),/Casa da minha mãe/);
  assert.match(await page.locator('#page-overview .page-heading p').innerText(),/presença da sua mãe/);
  // Pela configuração: salva no servidor e persiste ao recarregar.
  await page.evaluate(()=>window.setElderRelation('pai'));
  assert.match(await page.locator('.workspace').innerText(),/Casa do meu pai/);
  const s=await (await fetch(base+'/api/settings')).json();
  const saved=await fetch(base+'/api/settings',{method:'PUT',headers:{'Content-Type':'application/json','X-Casa-Request':'1'},body:JSON.stringify({...s,elder_relation:'avó'})});
  assert.equal(saved.status,200);
  await page.reload();await page.waitForSelector('#page-overview');await page.waitForTimeout(1200);
  assert.match(await page.locator('.workspace').innerText(),/Casa da minha avó/);
  const people=await (await fetch(base+'/api/people')).json();
  assert.ok(JSON.stringify(people).includes('Minha avó'),'perfil principal renomeado');
  // Texto digitado não muda.
  await page.goto(base+'/#messages');await page.waitForTimeout(500);
  await page.fill('#msg-text','Te amo, pai');
  assert.equal(await page.inputValue('#msg-text'),'Te amo, pai');
  assert.deepEqual(errors,[]);
  console.log('elder ui ok');
} finally { await browser?.close(); server.kill(); }
