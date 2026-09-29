import assert from 'node:assert/strict';
const base = 'http://127.0.0.1:8000';
const get = async path => (await fetch(base+path)).json();
await fetch(`${base}/api/monitor/start`,{method:'POST',headers:{'X-Casa-Request':'1'}});
let status;
for(let i=0;i<30;i++) {
  status = await get('/api/status');
  if(status.camera.state==='online') break;
  await new Promise(resolve=>setTimeout(resolve,1000));
}
assert.equal(status.camera.state,'online',JSON.stringify(status.camera));
const frame = await fetch(base+'/api/snapshot');
assert.equal(frame.status,200);
assert.equal(frame.headers.get('content-type'),'image/jpeg');
console.log(JSON.stringify({camera:status.camera,frameBytes:(await frame.arrayBuffer()).byteLength}));
assert.equal(status.recognition?.ready,true,JSON.stringify(status.recognition));
console.log(JSON.stringify({recognitionReady:status.recognition.ready,profiles:status.recognition.profiles.length,whatsapp:status.whatsapp.state}));
console.log('Câmera RTSP e inferência YOLO validadas. Monitoramento permanece ativo.');
