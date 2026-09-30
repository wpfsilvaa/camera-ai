import { proto } from '@whiskeysockets/baileys';

export async function resolveRecipient(socket, phone) {
  const results = await socket.onWhatsApp(phone);
  const match = results?.find(item => item.exists && typeof item.jid === 'string');
  if (!match) {
    const error = new Error('Número não encontrado no WhatsApp. Confira DDI e DDD.');
    error.code = 'RECIPIENT_NOT_FOUND';
    throw error;
  }
  return match.jid;
}

export function updateReceipt(ledger, key, status) {
  if (!key?.id || !Number.isInteger(status)) return false;
  const entry = Object.values(ledger).find(item => item.message_id === key.id);
  if (!entry) return false;
  if (status === 0) { entry.receipt_error = 'WhatsApp informou erro na mensagem.'; return true; }
  if (status <= (entry.ack_status || 0)) return false;
  entry.ack_status = status;
  entry.receipt = status >= 4 ? 'read' : status === 3 ? 'delivered' : status === 2 ? 'server' : 'pending';
  entry.receipt_at = Date.now();
  delete entry.receipt_error;
  return true;
}

export function savedMessage(ledger, key) {
  const entry = Object.values(ledger).find(item => item.message_id === key?.id);
  if (!entry?.message) return undefined;
  return proto.Message.decode(Buffer.from(entry.message, 'base64'));
}

export function encodeMessage(message) {
  return Buffer.from(proto.Message.encode(message).finish()).toString('base64');
}

// A clip can be sent once to each actual WhatsApp account. Different written
// phone formats resolving to the same JID must share a receipt.
export async function deliveryKey(ledger, clip, phone, jid, resolve) {
  const key = `${clip}:${jid}`;
  const legacy = ledger[clip];
  if (legacy) {
    const same = legacy.recipient === phone || legacy.resolved_jid === jid ||
      (!legacy.resolved_jid && legacy.recipient && await resolve(legacy.recipient) === jid);
    if (same) {
      ledger[key] ||= { ...legacy, resolved_jid: jid };
      delete ledger[clip];
    }
  }
  return key;
}

export function receiptEntries(ledger, clip, phone) {
  return Object.entries(ledger).filter(([key, value]) =>
    (key === clip || key.startsWith(`${clip}:`)) && (!phone || value.recipient === phone));
}
