export function validateRecipient(value) {
  if (!/^[0-9]{10,15}$/.test(value ?? '')) throw new Error('Destinatário inválido.');
  return value;
}

export function validateSend(body) {
  if (!body || !/^[a-f0-9]{32}$/.test(body.clip_id ?? '')) throw new Error('Vídeo inválido.');
  validateRecipient(body.recipient);
  if (typeof body.caption !== 'string' || body.caption.length > 1000) throw new Error('Legenda inválida.');
  return { clip_id: body.clip_id, recipient: body.recipient, caption: body.caption };
}

export function validateClip(body) {
  if (!/^[a-f0-9]{32}$/.test(body?.clip_id ?? '')) throw new Error('Vídeo inválido.');
  return body.clip_id;
}
