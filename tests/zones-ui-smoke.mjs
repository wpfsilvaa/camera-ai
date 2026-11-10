// The area editor (restricted areas, floor strips, fall areas): rectangles and polygons, moving, reshaping, undo, copying between cameras.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const data=await mkdtemp(path.join(tmpdir(),'zones-ui-'));
const base='http://127.0.0.1:18081';
const server=spawn('.venv/bin/python',['tests/manual_ui_server.py','18081'],{env:{...process.env,PYTHONPATH:'.',CAMERA_DATA_DIR:data,DASHBOARD_PASSWORD:'',WA_PORT:'18082'},stdio:['ignore','ignore','pipe']});
let logs='',browser;server.stderr.on('data',c=>logs+=c);
try {
  for(let i=0;i<200;i++){try{if((await fetch(base+'/api/settings')).ok)break;}catch{}if(i===199)throw Error(logs);await new Promise(r=>setTimeout(r,200));}
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/opt/google/chrome/chrome',headless:true,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1360,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const made=await (await fetch(base+'/api/cameras',{method:'POST',headers:{'Content-Type':'application/json','X-Casa-Request':'1'},body:JSON.stringify({camera_name:'Sala',camera_source:path.join(data,'input.avi'),enabled:true,analysis_enabled:false,restricted_zones:[[.1,.1,.4,.5],[.5,.5,.9,.9,.7,.95]],restricted_zone_names:['Armário','Canto']})})).json();
  assert.ok(made.id,JSON.stringify(made));
  await page.goto(`${base}/#settings`);await page.waitForTimeout(1500);
  const root=page.locator('.zone-editor[data-zones="restricted_zones"]'),canvas=root.locator('canvas');
  await root.scrollIntoViewIfNeeded();await page.waitForTimeout(600);
  const box=await canvas.boundingBox();
  const at=(fx,fy)=>[box.x+box.width*fx,box.y+box.height*fy];
  const zones=()=>page.evaluate(()=>window.zoneDrafts().restricted_zones);
  const click=(fx,fy)=>page.mouse.click(...at(fx,fy));
  const drag=async(a,b)=>{const [x1,y1]=at(...a),[x2,y2]=at(...b);await page.mouse.move(x1,y1);await page.mouse.down();await page.mouse.move((x1+x2)/2,(y1+y2)/2,{steps:4});await page.mouse.move(x2,y2,{steps:4});await page.mouse.up();};
  const tool=name=>root.locator(`[data-tool="${name}"]`).click();
  const undo=root.locator('[data-undo]');
  assert.equal(await undo.isDisabled(),true);
  // A polygon clicked out in four points, closed on the first one.
  await tool('poly');
  for(const p of [[.40,.20],[.60,.20],[.70,.90],[.30,.90]]) await click(...p);
  await click(.40,.20);
  let z=await zones();assert.equal(z.length,1);assert.equal(z[0].length,8);
  // A rectangle stays a rectangle; its body moves it; a corner turns it into a free quadrilateral.
  await tool('rect');await drag([.05,.10],[.25,.40]);
  z=await zones();assert.equal(z.length,2);assert.equal(z[1].length,4);
  await drag([.15,.25],[.20,.35]);
  const moved=(await zones())[1];assert.ok(Math.abs(moved[0]-.10)<.02&&Math.abs(moved[1]-.20)<.02,String(moved));
  await drag([moved[2],moved[3]],[moved[2]+.08,moved[3]+.1]);
  z=await zones();assert.equal(z[1].length,8);
  // Double click on an edge adds a corner, on a corner removes it.
  const corners=z[1].length/2,[ax,ay,bx,by]=z[1];
  await page.mouse.dblclick(...at((ax+bx)/2,(ay+by)/2));
  z=await zones();assert.equal(z[1].length/2,corners+1);
  await page.mouse.dblclick(...at(z[1][2],z[1][3]));
  z=await zones();assert.equal(z[1].length/2,corners);
  // Move everything (the camera was bumped), then nudge with the arrows.
  const first=(await zones())[0];
  await tool('all');await drag([.5,.5],[.55,.45]);
  z=await zones();assert.ok(Math.abs(z[0][0]-first[0]-.05)<.01);
  await canvas.focus();await page.keyboard.press('ArrowRight');
  assert.ok((await zones())[0][0]>z[0][0]);
  // Saved as numbers (a rectangle has 4, a polygon 8) and shown again after a reload.
  await page.locator('.settings-actions button.primary, #save-settings').first().click();await page.waitForTimeout(1500);
  const saved=await (await fetch(base+'/api/settings')).json();
  assert.deepEqual(saved.restricted_zones.map(a=>a.length),[8,8]);
  await page.reload();await page.waitForTimeout(1500);
  assert.equal((await page.evaluate(()=>window.zoneDrafts().restricted_zones)).length,2);

  // Undo, a crossing polygon, a corner that would cross, Ctrl+Z, copy from another camera.
  await root.scrollIntoViewIfNeeded();await page.waitForTimeout(500);
  await root.locator('[data-zone-clear]').click();
  assert.equal(await undo.isDisabled(),false);await undo.click();assert.equal((await zones()).length,2);   // Clearing can be undone.
  await root.locator('[data-zone-clear]').click();
  await tool('poly');
  for(const p of [[.2,.2],[.6,.6],[.65,.25],[.25,.55]]) await click(...p);   // The edges cross.
  await click(.2,.2);
  z=await zones();assert.equal(z.length,1);assert.equal(z[0].length,8);
  const turn=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]),pts=[0,2,4,6].map(i=>[z[0][i],z[0][i+1]]);
  for(let i=0;i<4;i++)for(let j=i+2;j<4;j++){if(i===0&&j===3)continue;const [a,b,c,d]=[pts[i],pts[(i+1)%4],pts[j],pts[(j+1)%4]];assert.ok(!(turn(a,b,c)*turn(a,b,d)<0&&turn(c,d,a)*turn(c,d,b)<0),'corners were put in order');}
  const quad=JSON.stringify(z);
  await drag([z[0][4],z[0][5]],[.3,.1]);
  assert.equal(JSON.stringify(await zones()),quad,'a corner that would make the edges cross goes back');
  await tool('rect');await canvas.focus();await drag([.7,.8],[.9,.95]);
  const total=(await zones()).length;await page.keyboard.press('Control+z');assert.equal((await zones()).length,total-1);
  await page.waitForTimeout(3000);
  const copy=root.locator('[data-copy]');assert.equal(await copy.isVisible(),true);
  await copy.selectOption(made.id);await page.waitForTimeout(800);
  assert.equal((await zones()).length,total-1+2);
  assert.deepEqual((await page.$$eval('[data-zone-name]',i=>i.map(x=>x.value))).slice(-2),['Armário','Canto']);
  await undo.click();assert.equal((await zones()).length,total-1);
  assert.deepEqual(errors,[]);
  console.log('PASS: editor de áreas: polígono, retângulo, mover, deformar, adicionar/remover canto, mover todas, setas, salvar, desfazer, polígono cruzado e cópia entre câmeras.');
} finally {await browser?.close();server.kill();}
