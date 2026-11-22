// Quadrinhos: painel (ligar, reordenar pelas setas e arrastando, frases, remédios, prévia, salvar) e tela do totem (ordem, relógio, frase, foto, remédio).
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const data=await mkdtemp(path.join(tmpdir(),'kiosk-widgets-ui-'));
const base='http://127.0.0.1:18107', kiosk='http://127.0.0.1:18109';
const server=spawn('.venv/bin/python',['tests/manual_ui_server.py','18107'],{env:{...process.env,PYTHONPATH:'.',CAMERA_DATA_DIR:data,DASHBOARD_PASSWORD:'',WA_PORT:'18108'},stdio:['ignore','ignore','pipe']});
const files=spawn('python3',['-m','http.server','18109','--bind','127.0.0.1'],{cwd:'notebook/kiosk',stdio:'ignore'});
let logs='',browser;server.stderr.on('data',c=>logs+=c);
try {
  for(let i=0;i<200;i++){try{if((await fetch(base+'/api/settings')).ok)break;}catch{}if(i===199)throw Error(logs);await new Promise(r=>setTimeout(r,200));}
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
  // ---------- painel ----------
  const page=await browser.newPage({viewport:{width:1360,height:1200}});
  await page.goto(base+'/#settings');await page.waitForSelector('#settings-form [name=camera_source]',{state:'attached'});
  await page.evaluate(()=>document.querySelector('[role=tab][data-group=totem]').click());
  const panel=page.locator('#kiosk-widgets-panel');await panel.scrollIntoViewIfNeeded();
  const rowIds=()=>panel.locator('.wg-row').evaluateAll(rows=>rows.map(r=>r.dataset.id));
  const csv=()=>panel.locator('[name=kiosk_widgets]').inputValue();
  assert.deepEqual(await rowIds(),['calendar','clock','quote','photo','medication']);
  assert.equal(await csv(),'calendar,-clock,-quote,-photo,-medication');
  await panel.locator('.wg-row[data-id=clock] [data-wg-on]').check();
  await panel.locator('.wg-row[data-id=medication] [data-wg-on]').check();
  await panel.locator('.wg-row[data-id=medication] [data-wg-up]').click();   // medication sobe uma posição
  await panel.locator('.wg-row[data-id=medication] [data-wg-up]').click();
  assert.deepEqual(await rowIds(),['calendar','clock','medication','quote','photo']);
  assert.equal(await csv(),'calendar,clock,medication,-quote,-photo');   // O calendário nunca leva "-": liga e desliga pela chave própria.
  // arrastar: clock para o topo
  await panel.locator('.wg-row[data-id=clock]').dragTo(panel.locator('.wg-row[data-id=calendar]'));
  assert.deepEqual((await rowIds()).slice(0,3),['clock','calendar','medication'],'arrastar deveria reordenar');
  // calendário: a chave de lá e a chave "Mostrar o calendário" andam juntas
  await panel.locator('.wg-row[data-id=calendar] [data-wg-on]').uncheck();
  assert.equal(await page.locator('[name=kiosk_calendar_enabled]').isChecked(),false);
  await panel.locator('.wg-row[data-id=calendar] [data-wg-on]').check();
  assert.equal(await page.locator('[name=kiosk_calendar_enabled]').isChecked(),true);
  // prévia
  const order=await page.locator('#tp-board').evaluate(b=>[...b.children].filter(c=>!c.hidden).sort((a,b)=>+a.style.order-+b.style.order).map(c=>c.dataset.tw||'calendar'));
  assert.deepEqual(order,['clock','calendar','medication']);
  // textos
  await panel.locator('[name=kiosk_quotes]').fill('Frase um\nFrase dois');
  await panel.locator('[name=kiosk_medications]').fill('08:00 Losartana 50 mg\nerrada\n21:30 Vitamina D');
  assert.match(await page.locator('#wg-meds-note').textContent(),/Entendi 2 horário\(s\)\. 1 linha\(s\) ignorada/);
  await page.locator('#save-settings').click();await page.waitForSelector('.toast');
  const saved=await fetch(base+'/api/settings').then(r=>r.json());
  assert.equal(saved.kiosk_widgets,'clock,calendar,medication,-quote,-photo');
  assert.deepEqual(saved.kiosk_quotes,['Frase um','Frase dois']);
  assert.deepEqual(saved.kiosk_medications,['08:00 Losartana 50 mg','errada','21:30 Vitamina D']);
  await page.screenshot({path:'test-results/kiosk-widgets-panel.png'});
  await page.reload();await page.waitForSelector('#settings-form [name=camera_source]',{state:'attached'});
  await page.evaluate(()=>document.querySelector('[role=tab][data-group=totem]').click());
  await page.waitForTimeout(900);
  assert.deepEqual((await rowIds()).slice(0,3),['clock','calendar','medication'],'a ordem deveria voltar depois de recarregar');
  assert.equal(await page.locator('#kiosk-widgets-panel .wg-row[data-id=clock] [data-wg-on]').isChecked(),true);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'rolagem lateral');
  await page.close();
  // ---------- totem ----------
  const jpg=await readFile('tests/assets/messi5.jpg');
  const stateBase={vigia:'resting',night:false,call:{state:'idle',seq:1},enabled:{call:true,panic:true},linked:true,present:[],bdays:[],callto:[],reminders:[],battery:80,plugged:true,photos:[{id:'a'.repeat(32),a:'Ana'}]};
  async function screen(widgets,viewport={width:1366,height:768},time='2026-11-22T13:40:00'){
    const p=await browser.newPage({viewport});
    await p.clock.install({time:new Date(time)});
    await p.route('**/photo/*',r=>r.fulfill({contentType:'image/jpeg',body:jpg}));
    await p.route('**/state**',r=>r.fulfill({contentType:'application/json',body:JSON.stringify({...stateBase,cfg:{widgets}})}));
    await p.goto(kiosk+'/index.html');await p.waitForTimeout(1300);return p;
  }
  const widgets={order:['photo','medication','quote','clock','calendar'],quotes:['Frase um','Frase dois'],meds:['08:00 Losartana','14:00 Metformina']};
  let t=await screen(widgets);
  const geo=await t.evaluate(()=>({count:document.getElementById('board').dataset.count,tiles:[...document.querySelectorAll('.board>.tile:not(.hidden)')].map(x=>[x.dataset.w,+x.style.order,x.classList.contains('wide')]).sort((a,b)=>a[1]-b[1]).map(x=>x[0]+(x[2]?'*':'')),
    med:[document.getElementById('med-name').textContent,document.getElementById('med-when').textContent,document.querySelector('.med-tile').classList.contains('soon')],
    quote:document.getElementById('qday').textContent,photo:document.getElementById('ptile').getAttribute('src'),hands:['ah','am','as'].map(i=>document.getElementById(i).getAttribute('transform')),
    inside:[...document.querySelectorAll('.board>.tile:not(.hidden)')].every(x=>{const r=x.getBoundingClientRect();return r.right<=innerWidth&&r.bottom<=innerHeight&&r.left>=0}),
    panicBottom:document.getElementById('btn-panic').getBoundingClientRect().bottom,vh:innerHeight}));
  assert.deepEqual(geo.tiles,['photo','medication','quote','clock','calendar*'],'ordem e o quadrinho sobrando em linha inteira');
  assert.deepEqual(geo.med,['Metformina','às 14:00 · em 20 min',true]);
  assert.match(geo.quote,/^Frase (um|dois)$/);
  assert.match(geo.photo,/^\/photo\/a{32}\.jpg$/);
  const [hour,minute,second]=geo.hands.map(x=>parseFloat(/rotate\(([\d.]+)/.exec(x)[1]));   // O relógio da página anda: 13:40:0x.
  assert.ok(Math.abs(hour-50)<1&&Math.abs(minute-240)<3&&second>=0&&second<=30,`ponteiros fora do esperado: ${geo.hands}`);
  assert.ok(geo.inside,'um quadrinho passou da tela');assert.ok(geo.panicBottom<=geo.vh);
  await t.close();
  // 13:40 → às 14:00; 14:10 → "agora" (dentro de 30 min depois do horário); 22:00 → amanhã às 08:00
  for(const [time,when] of [['2026-11-22T14:10:00','agora'],['2026-11-22T22:00:00','amanhã, às 08:00 · em 10 h']]){
    t=await screen({order:['medication'],quotes:[],meds:['08:00 Losartana','14:00 Metformina']},{width:1024,height:600},time);
    assert.equal(await t.locator('#med-when').textContent(),when);
    await t.close();
  }
  t=await screen({order:['calendar'],quotes:[],meds:[]},{width:1024,height:600});   // Só o calendário: o visual de sempre.
  assert.equal(await t.evaluate(()=>document.getElementById('board').hasAttribute('data-fixed')),false);
  assert.equal(await t.locator('.cal-next').isVisible(),true);
  await t.close();
  t=await screen({order:[],quotes:[],meds:[]});
  assert.equal(await t.locator('#board').isVisible(),false);
  await t.close();
  console.log('PASS: quadrinhos: ligar, reordenar (setas e arrastar), calendário sincronizado, frases e remédios; a tela do totem respeita ordem, relógio, frase, foto e remédio.');
} finally { await browser?.close(); server.kill(); files.kill(); }
