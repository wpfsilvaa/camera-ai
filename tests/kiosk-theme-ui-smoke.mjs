// Aparência da tela: painel (paleta, cores, tamanho, o que aparece, pré-visualização, aviso de contraste) e tela do totem (aplica; à noite mantém o vermelho).
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const data=await mkdtemp(path.join(tmpdir(),'kiosk-theme-ui-'));
const base='http://127.0.0.1:18103', kiosk='http://127.0.0.1:18105';
const server=spawn('.venv/bin/python',['tests/manual_ui_server.py','18103'],{env:{...process.env,PYTHONPATH:'.',CAMERA_DATA_DIR:data,DASHBOARD_PASSWORD:'',WA_PORT:'18104'},stdio:['ignore','ignore','pipe']});
const files=spawn('python3',['-m','http.server','18105','--bind','127.0.0.1'],{cwd:'notebook/kiosk',stdio:'ignore'});
let logs='',browser;server.stderr.on('data',c=>logs+=c);
try {
  for(let i=0;i<200;i++){try{if((await fetch(base+'/api/settings')).ok)break;}catch{}if(i===199)throw Error(logs);await new Promise(r=>setTimeout(r,200));}
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
  // ---------- painel ----------
  const page=await browser.newPage({viewport:{width:1360,height:1100}});
  await page.goto(base+'/#settings');await page.waitForSelector('#settings-form [name=camera_source]',{state:'attached'});
  await page.evaluate(()=>document.querySelector('[role=tab][data-group=totem]').click());
  const panel=page.locator('#kiosk-theme-panel');await panel.scrollIntoViewIfNeeded();
  assert.equal(await panel.isVisible(),true);
  const css=name=>page.locator('#totem-preview').evaluate((el,n)=>el.style.getPropertyValue(n),name);
  await panel.locator('[name=kiosk_palette]').selectOption('claro');
  assert.equal(await css('--bg'),'#f3f6f7');
  assert.equal(await panel.locator('[name=kiosk_color_bg]').inputValue(),'#f3f6f7','a paleta pronta deveria preencher as cores');
  await panel.locator('[name=kiosk_color_call]').fill('#ffee00');   // cor própria muito clara para o texto branco
  assert.equal(await panel.locator('[name=kiosk_palette]').inputValue(),'personalizada');
  assert.match(await page.locator('#theme-warning').textContent(),/Chamar a família.*claro demais/);
  await panel.locator('[name=kiosk_color_call]').fill('#0f6b82');
  assert.equal(await page.locator('#theme-warning').textContent(),'');
  await panel.locator('[name=kiosk_text_size]').selectOption('grande');
  assert.equal(await page.locator('#totem-preview').getAttribute('data-size'),'grande');
  await panel.locator('[name=kiosk_show_weather]').uncheck();
  assert.equal(await page.locator('#totem-preview [data-tp=weather]').isVisible(),false);
  await panel.locator('[name=kiosk_show_holidays]').uncheck();
  await page.locator('#save-settings').click();await page.waitForSelector('.toast');
  const saved=await fetch(base+'/api/settings').then(r=>r.json());
  assert.deepEqual([saved.kiosk_palette,saved.kiosk_color_bg,saved.kiosk_color_call,saved.kiosk_text_size,saved.kiosk_show_weather,saved.kiosk_show_holidays,saved.kiosk_show_date],['personalizada','#f3f6f7','#0f6b82','grande',false,false,true]);
  await page.screenshot({path:'test-results/kiosk-theme-panel.png'});
  await panel.locator('#kiosk-theme-reset').click();
  assert.equal(await panel.locator('[name=kiosk_palette]').inputValue(),'padrao');
  assert.equal(await panel.locator('[name=kiosk_show_weather]').isChecked(),true);
  assert.equal(await panel.locator('[name=kiosk_text_size]').inputValue(),'normal');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'rolagem lateral no painel');
  await page.close();
  // ---------- totem ----------
  const stateBase={vigia:'resting',call:{state:'idle',seq:1},enabled:{call:true,panic:true},linked:true,present:['Flavio'],weather:{at:Date.now()/1000,t:27,text:'Nublado',icon:'cloud',days:[{hi:28,lo:19,rain:10}]},bdays:[],callto:[],reminders:[],battery:80,plugged:true};
  const theme={colors:{bg:'#f3f6f7',ink:'#13232b',call:'#0f6b82',panic:'#c43a2f',accent:'#a86a00'},size:'grande',show:{weather:false,battery:false,holidays:false}};
  async function screen(extra,viewport={width:1024,height:600}){
    const p=await browser.newPage({viewport});
    await p.route('**/state**',r=>r.fulfill({contentType:'application/json',body:JSON.stringify({...stateBase,...extra})}));
    await p.goto(kiosk+'/index.html');await p.waitForTimeout(1200);return p;
  }
  let t=await screen({night:false,red:false,cfg:{theme}});
  assert.equal(await t.evaluate(()=>getComputedStyle(document.body).backgroundColor),'rgb(243, 246, 247)');
  assert.equal(await t.evaluate(()=>getComputedStyle(document.querySelector('.call')).backgroundColor),'rgb(15, 107, 130)');
  assert.equal(await t.evaluate(()=>document.documentElement.dataset.size),'grande');
  assert.equal(await t.locator('#ui-weather').isVisible(),false);
  assert.equal(await t.locator('#battery').isVisible(),false);
  assert.equal(await t.locator('.cal-next').isVisible(),false);
  assert.equal(await t.locator('#present').isVisible(),true);
  assert.ok(await t.evaluate(()=>document.querySelector('#btn-panic').getBoundingClientRect().bottom<=innerHeight),'o botão de ajuda passou da tela com texto grande em 1024x600');
  await t.close();
  t=await screen({night:true,red:true,cfg:{theme}});   // À noite os tons vermelhos prevalecem.
  assert.equal(await t.evaluate(()=>document.documentElement.dataset.night),'1');
  assert.equal(await t.evaluate(()=>getComputedStyle(document.body).backgroundColor),'rgb(8, 2, 2)');
  await t.close();
  t=await screen({cfg:{}});
  assert.equal(await t.evaluate(()=>getComputedStyle(document.body).backgroundColor),'rgb(13, 21, 25)','sem tema, o visual padrão');
  await t.close();
  console.log('PASS: aparência da tela: paleta, cores próprias, contraste, tamanho, itens e pré-visualização; o totem aplica e à noite mantém o vermelho.');
} finally { await browser?.close(); server.kill(); files.kill(); }
