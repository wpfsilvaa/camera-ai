import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resolveRecipient, updateReceipt, savedMessage, encodeMessage } from './delivery.mjs';

test('send to the canonical WhatsApp address, including Brazilian ninth digit normalization', async () => {
  const socket={onWhatsApp:async phone=>{
    assert.equal(phone,'5511999999999');
    return [{exists:true,jid:'551199999999@s.whatsapp.net'}];
  }};
  assert.equal(await resolveRecipient(socket,'5511999999999'),'551199999999@s.whatsapp.net');
  await assert.rejects(resolveRecipient({onWhatsApp:async()=>[]},'5511999999999'));
});

test('record actual receipts without downgrading or affecting unrelated messages', () => {
  const ledger={clip:{state:'sent',message_id:'m1'}};
  assert.equal(updateReceipt(ledger,{id:'other'},3),false);
  assert.equal(updateReceipt(ledger,{id:'m1'},2),true);
  assert.equal(ledger.clip.receipt,'server');
  updateReceipt(ledger,{id:'m1'},3);
  assert.equal(ledger.clip.receipt,'delivered');
  updateReceipt(ledger,{id:'m1'},4);
  assert.equal(ledger.clip.receipt,'read');
  assert.equal(updateReceipt(ledger,{id:'m1'},2),false);
  assert.equal(ledger.clip.receipt,'read');
});

test('persist media messages for Baileys decryption retry requests', () => {
  const encoded=encodeMessage({videoMessage:{url:'https://example.test/video',caption:'Test',mimetype:'video/mp4',mediaKey:Buffer.from([1,2,3])}});
  const ledger=JSON.parse(JSON.stringify({clip:{message_id:'m1',message:encoded}}));
  const restored=savedMessage(ledger,{id:'m1'});
  assert.equal(restored.videoMessage.caption,'Test');
  assert.deepEqual(Buffer.from(restored.videoMessage.mediaKey),Buffer.from([1,2,3]));
  assert.equal(savedMessage(ledger,{id:'unknown'}),undefined);
});

test('one receipt per clip and canonical account, including old ledger migration', async () => {
  const { deliveryKey } = await import('./delivery.mjs');
  const clip='a'.repeat(32), primary='5511999999999', sister='5511888888888';
  const canonical='551199999999@s.whatsapp.net', other='551188888888@s.whatsapp.net';
  const resolve=async phone=>phone===primary?canonical:other;
  const ledger={[clip]:{recipient:primary,state:'sent',message_id:'original'}};
  const sisterKey=await deliveryKey(ledger,clip,sister,other,resolve);
  assert.equal(ledger[sisterKey],undefined,'legacy success must not suppress sister delivery');
  const primaryKey=await deliveryKey(ledger,clip,primary,canonical,resolve);
  assert.equal(ledger[primaryKey].message_id,'original');
  assert.equal(ledger[clip],undefined);
  assert.equal(await deliveryKey(ledger,clip,'551199999999',canonical,resolve),primaryKey);
  ledger[sisterKey]={recipient:sister,state:'uncertain',message_id:'sister'};
  updateReceipt(ledger,{id:'original'},3);
  assert.equal(ledger[primaryKey].receipt,'delivered');
  assert.equal(ledger[sisterKey].receipt,undefined);
});

test('retry selection is restricted to the requested recipient', async () => {
  const { receiptEntries }=await import('./delivery.mjs');
  const ledger={'clip:a':{recipient:'111',state:'sent'},'clip:b':{recipient:'222',state:'uncertain'},'other:a':{recipient:'222',state:'uncertain'}};
  assert.deepEqual(receiptEntries(ledger,'clip','222').map(([key])=>key),['clip:b']);
});
