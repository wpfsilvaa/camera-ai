import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const token = (await readFile('data/gateway.token','utf8')).trim();
const base = 'http://127.0.0.1:3001';
assert.equal((await fetch(base+'/status')).status,401);
const headers = {'Authorization':`Bearer ${token}`,'Content-Type':'application/json'};
assert.equal((await fetch(base+'/send',{method:'POST',headers,body:JSON.stringify({clip_id:'../private',recipient:'123',caption:''})})).status,400);
await fetch(base+'/connect',{method:'POST',headers});
let state;
for(let i=0;i<25;i++) {
  state = await (await fetch(base+'/status',{headers})).json();
  if(state.state==='qr' || state.state==='connected') break;
  await new Promise(resolve=>setTimeout(resolve,1000));
}
assert.ok(['qr','connected'].includes(state.state),JSON.stringify({state:state.state,error:state.error}));
if(state.state==='qr') assert.ok(state.qr.startsWith('data:image/png;base64,'));
console.log(`Gateway protegido, validação de arquivos e conexão Baileys OK (${state.state}). Nenhuma mensagem enviada.`);
