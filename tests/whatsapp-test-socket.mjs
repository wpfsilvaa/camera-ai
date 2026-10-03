// This module is loaded only by the isolated test hook, never by production.
export * from '../node_modules/@whiskeysockets/baileys/lib/index.js';
import {EventEmitter} from 'node:events';
import {appendFile} from 'node:fs/promises';
import path from 'node:path';
export default function makeSocket(){
  const ev=new EventEmitter();queueMicrotask(()=>ev.emit('connection.update',{connection:'open'}));
  return {ev,user:{id:'551166666666@s.whatsapp.net'},end(){},
    async onWhatsApp(phone){return [{exists:true,jid:(phone.length===13?phone.slice(0,4)+phone.slice(5):phone)+'@s.whatsapp.net'}];},
    async sendMessage(jid,content,options){
      await appendFile(path.join(process.env.CAMERA_DATA_DIR,'test-sends.jsonl'),JSON.stringify({jid,id:options.messageId,kind:Object.keys(content)[0]})+'\n');
      if(jid==='551177777777@s.whatsapp.net')throw Error('simulated upload failure');
      ev.emit('messages.update',[{key:{id:options.messageId,fromMe:true,remoteJid:jid},update:{status:3}}]);
      return {key:{id:options.messageId},message:{videoMessage:{url:'https://example.invalid/test',caption:content.caption,mimetype:'video/mp4'}}};
    }
  };
}
