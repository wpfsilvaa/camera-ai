// Configurações da câmera por tipo de fonte: etiqueta (USB/rede/vídeo), painel de imagem só quando há suporte e detecção avançada recolhida.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const data=await mkdtemp(path.join(tmpdir(),'camera-kind-ui-'));
const base='http://127.0.0.1:18085';
const server=spawn('.venv/bin/python',['tests/manual_ui_server.py','18085'],{env:{...process.env,PYTHONPATH:'.',CAMERA_DATA_DIR:data,DASHBOARD_PASSWORD:'',WA_PORT:'18086'},stdio:['ignore','ignore','pipe']});
let logs='',browser;server.stderr.on('data',c=>logs+=c);
try {
  for(let i=0;i<200;i++){try{if((await fetch(base+'/api/settings')).ok)break;}catch{}if(i===199)throw Error(logs);await new Promise(r=>setTimeout(r,200));}
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
  for(const theme of ['light','dark']) {
    const page=await browser.newPage({viewport:{width:1360,height:900},colorScheme:theme});
    await page.goto(base+'/#settings');await page.waitForSelector('#settings-form [name=camera_source]');
    const source=page.locator('#settings-form [name=camera_source]');
    for(const [value,label] of [['rtsp://192.168.1.50:554/stream1','Câmera de rede (RTSP)'],['usb:/dev/video0','Câmera USB'],['/tmp/teste.avi','Vídeo local']]) {
      await source.fill(value);
      await page.waitForFunction(text=>document.querySelector('#source-kind').textContent===text,label);
    }
    await source.fill('rtsp://192.168.1.50:554/stream1');
    await page.waitForFunction(()=>document.querySelector('#settings-form').dataset.source==='rtsp');
    assert.equal(await page.locator('#settings-form .usb-only').first().isVisible(),false,'dica de USB aparece com RTSP');
    assert.equal(await page.locator('#image-panel').isVisible(),false,'painel de imagem aparece sem suporte');
    assert.equal(await page.locator('#settings-form [name=device]').isVisible(),false,'ajustes avançados deveriam estar recolhidos');
    assert.equal(await page.locator('#settings-form [name=detection_fps]').isVisible(),true,'quadros por segundo deve ficar à vista');
    await page.locator('#settings-form summary:has-text("Ajustes de detecção")').click();
    assert.equal(await page.locator('#settings-form [name=device]').isVisible(),true);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'rolagem lateral');
    await page.screenshot({path:`test-results/camera-kind-${theme}.png`});
    await page.close();
  }
  console.log('PASS: etiqueta do tipo de fonte, painel de imagem escondido sem suporte, detecção avançada recolhida (claro e escuro).');
} finally { await browser?.close(); server.kill(); }
