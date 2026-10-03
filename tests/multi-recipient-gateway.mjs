import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,mkdir,readFile,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
const data=await mkdtemp(path.join(tmpdir(),'gateway-multi-'));
const clip='a'.repeat(32),old='b'.repeat(32),primary='5511999999999',sister='5511888888888',failure='5511777777777';
await mkdir(path.join(data,'clips'));
for(const id of [clip,old])await writeFile(path.join(data,'clips',id+'.mp4'),'test fixture');
await writeFile(path.join(data,'whatsapp-delivery.json'),JSON.stringify({[old]:{state:'sent',recipient:primary,message_id:'legacy'}}));
const server=spawn(process.execPath,['--import','./tests/whatsapp-test-hook.mjs','whatsapp/server.mjs'],{env:{...process.env,CAMERA_DATA_DIR:data,WA_PORT:'18041'},stdio:['ignore','ignore','pipe']});
let logs='';server.stderr.on('data',c=>logs+=c);
try{
 let headers;
 for(let n=0;n<100;n++){
  try{headers={'Authorization':'Bearer '+(await readFile(path.join(data,'gateway.token'),'utf8')).trim(),'Content-Type':'application/json'};if((await fetch('http://127.0.0.1:18041/status',{headers})).ok)break;}catch{}
  if(n===99)throw Error(logs);await new Promise(r=>setTimeout(r,100));
 }
 const post=(route,body)=>fetch('http://127.0.0.1:18041'+route,{method:'POST',headers,body:JSON.stringify(body)});
 await post('/connect',{});
 const send=(recipient,id=clip)=>post('/send',{clip_id:id,recipient,caption:'Isolated test'});
 const responses=await Promise.all([send(primary),send(primary),send(sister)]);
 assert.equal(responses[2].status,200);
 assert.ok(responses.slice(0,2).some(r=>r.status===200));
 assert.equal((await send('551199999999')).status,200,'same canonical account is idempotent');
 assert.equal((await send(failure)).status,409);
 assert.equal((await post('/retry',{clip_id:clip,recipient:'551177777777'})).status,200);
 assert.equal((await send(failure)).status,409);
 assert.equal((await send(primary,old)).status,200);
 assert.equal((await send(sister,old)).status,200,'old receipt must not suppress another recipient');
 const alert=body=>post('/text',{alert_id:'offline-main-1759000000',text:'Câmera sem imagem.',...body});
 const firstAlert=await alert({recipient:primary});
 assert.equal(firstAlert.status,200);
 assert.equal((await alert({recipient:primary})).status,200,'alert text is idempotent');
 assert.equal((await alert({recipient:sister})).status,200);
 assert.equal((await alert({recipient:primary,alert_id:'../bad'})).status,400);
 await mkdir(path.join(data,'alerts'));await writeFile(path.join(data,'alerts','fall-main-1759000000.jpg'),'jpeg');
 assert.equal((await alert({recipient:primary,alert_id:'fall-main-1759000000',image:true})).status,200,'photo alert');
 assert.equal((await alert({recipient:primary,alert_id:'fall-main-1759000001',image:true})).status,200,'missing photo still sends text');
 const rows=(await readFile(path.join(data,'test-sends.jsonl'),'utf8')).trim().split('\n').map(JSON.parse);
 assert.equal(rows.filter(r=>r.jid==='551199999999@s.whatsapp.net').length,4,'one clip and three alerts');
 assert.equal(rows.filter(r=>r.jid==='551188888888@s.whatsapp.net').length,3);
 assert.deepEqual(rows.slice(-2).map(r=>r.kind),['image','text'],'photo when present, text otherwise');
 assert.equal(rows.filter(r=>r.jid==='551177777777@s.whatsapp.net').length,2);
 const receipt=await (await post('/delivery',{clip_id:clip,recipient:primary})).json();
 assert.equal(receipt.receipt,'delivered');
 console.log('Gateway HTTP validado: concorrência, dois destinatários, número canônico, migração antiga, falha isolada, reenvio seletivo, alertas de texto e foto idempotentes e confirmações. Baileys simulado; nenhum envio real.');
}finally{
 server.kill('SIGTERM');await new Promise(resolve=>{server.once('exit',resolve);setTimeout(()=>{server.kill('SIGKILL');resolve();},3000).unref();});
 await rm(data,{recursive:true,force:true});
}
