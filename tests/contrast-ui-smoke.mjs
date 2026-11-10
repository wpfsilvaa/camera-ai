// Contraste (WCAG AA) do texto visível nas telas principais, nos temas claro e escuro, no celular e no computador.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const data=await mkdtemp(path.join(tmpdir(),'contrast-ui-'));
const base='http://127.0.0.1:18087';
const server=spawn('.venv/bin/python',['tests/history_nav_ui_server.py','18087'],{env:{...process.env,PYTHONPATH:'.',CAMERA_DATA_DIR:data,DASHBOARD_PASSWORD:'',WA_PORT:'18088'},stdio:['ignore','ignore','pipe']});
let logs='',browser;server.stderr.on('data',c=>logs+=c);
const scan=()=>{
  const parse=s=>{const m=s.match(/rgba?\(([^)]+)\)/);if(!m)return null;const [r,g,b,a=1]=m[1].split(/[ ,\/]+/).filter(Boolean).map(Number);return {r,g,b,a};};
  const lum=({r,g,b})=>{const f=v=>{v/=255;return v<=.03928?v/12.92:((v+.055)/1.055)**2.4};return .2126*f(r)+.7152*f(g)+.0722*f(b);};
  const ratio=(a,b)=>{const x=lum(a),y=lum(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);};
  const bgOf=el=>{for(let e=el;e;e=e.parentElement){const s=getComputedStyle(e);if(s.backgroundImage!=='none')return null;const c=parse(s.backgroundColor);if(c&&c.a>=.99)return c;if(c&&c.a>0)return null;}return {r:255,g:255,b:255,a:1};};
  const bad=[];let seen=0;
  for(const el of document.querySelectorAll('body *')){
    if(!el.offsetParent&&getComputedStyle(el).position!=='fixed')continue;
    if(![...el.childNodes].some(n=>n.nodeType===3&&n.textContent.trim()))continue;
    const s=getComputedStyle(el);if(s.visibility==='hidden'||Number(s.opacity)<1||s.fontSize==='0px')continue;
    const rect=el.getBoundingClientRect();if(rect.width<2||rect.height<2)continue;
    const bg=bgOf(el);if(!bg)continue;const fg=parse(s.color);if(!fg||fg.a<1)continue;
    const big=parseFloat(s.fontSize)>=24||(parseFloat(s.fontSize)>=18.66&&Number(s.fontWeight)>=700);
    seen++;const need=big?3:4.5,got=ratio(fg,bg);
    if(got<need-.01)bad.push(`${el.tagName.toLowerCase()}.${(el.className||'').toString().split(' ')[0]} "${el.textContent.trim().slice(0,28)}" ${got.toFixed(2)}<${need}`);
  }
  window.__seen=seen;return [...new Set(bad)];
};
try {
  for(let i=0;i<200;i++){try{if((await fetch(base+'/api/settings')).ok)break;}catch{}if(i===199)throw Error(logs);await new Promise(r=>setTimeout(r,200));}
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
  const failures=[];
  for(const theme of ['light','dark']) for(const [w,h] of [[1360,900],[390,844]]) {
    const page=await browser.newPage({viewport:{width:w,height:h},colorScheme:theme});
    for(const hash of ['overview','history','people','messages','health','settings','users']) {
      await page.goto(`${base}/#${hash}`);await page.waitForTimeout(900);
      for(const msg of await page.evaluate(scan)) failures.push(`${theme} ${w}px #${hash}: ${msg}`);
      const seen=await page.evaluate(()=>window.__seen);if(process.env.V)console.log(theme,w,hash,'examinados',seen);assert.ok(seen>=3,`pouco texto examinado em #${hash}: ${seen}`);
    }
    await page.close();
  }
  if(failures.length){console.log(failures.join('\n'));}
  assert.equal(failures.length,0,`${failures.length} pares de texto abaixo do mínimo de contraste`);
  console.log('contraste ok');
} finally { await browser?.close(); server.kill(); }
