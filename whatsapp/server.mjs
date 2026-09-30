import 'dotenv/config';
import http from 'node:http';
import { mkdir, readFile, writeFile, rename, stat, realpath } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomBytes, timingSafeEqual } from 'node:crypto';
import makeWASocket, { DisconnectReason, useMultiFileAuthState, makeCacheableSignalKeyStore, generateMessageIDV2 } from '@whiskeysockets/baileys';
import QRCode from 'qrcode';
import pino from 'pino';
import { validateSend, validateClip, validateRecipient, validateText } from './validation.mjs';
import { resolveRecipient, updateReceipt, savedMessage, encodeMessage, deliveryKey, receiptEntries } from './delivery.mjs';

process.umask(0o077);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const data = path.resolve(process.env.CAMERA_DATA_DIR || path.join(root, 'data'));
const clips = path.join(data, 'clips');
await mkdir(clips, { recursive: true });
const tokenPath = path.join(data, 'gateway.token');
try { await writeFile(tokenPath, randomBytes(32).toString('hex'), { flag: 'wx', mode: 0o600 }); }
catch (error) { if (error.code !== 'EEXIST') throw error; }
const token = (await readFile(tokenPath, 'utf8')).trim();
const ledgerPath = path.join(data, 'whatsapp-delivery.json');
let ledger = {};
try { ledger = JSON.parse(await readFile(ledgerPath, 'utf8')); }
catch (error) { if (error.code !== 'ENOENT') throw error; }
// A process may have stopped after WhatsApp accepted an upload.
for (const entry of Object.values(ledger)) if (entry.state === 'sending') entry.state = 'uncertain';
let saveChain = Promise.resolve();
function persist() {
  saveChain = saveChain.catch(() => {}).then(async () => {
    await writeFile(`${ledgerPath}.tmp`, JSON.stringify(ledger), { mode: 0o600 });
    await rename(`${ledgerPath}.tmp`, ledgerPath);
  });
  return saveChain;
}
const logger = pino({ level: 'silent' });
let socket, reconnectTimer, shuttingDown = false, connecting = false;
let state = 'disconnected', qr = null, statusError = null, generation = 0;
const authDir = path.join(data, 'whatsapp-auth');

async function connect() {
  if (connecting || ['connected', 'connecting', 'qr'].includes(state)) return;
  connecting = true;
  state = 'connecting'; statusError = null;
  const currentGeneration = ++generation;
  try {
    const { state: auth, saveCreds } = await useMultiFileAuthState(authDir);
    socket = makeWASocket({
      auth: { creds: auth.creds, keys: makeCacheableSignalKeyStore(auth.keys, logger) },
      logger, markOnlineOnConnect: false, syncFullHistory: false,
      shouldSyncHistoryMessage: () => false,
      generateHighQualityLinkPreview: false,
      getMessage: async key => savedMessage(ledger, key),
    });
    socket.ev.on('creds.update', () => saveCreds().catch(() => { statusError = 'Falha ao salvar a sessão do WhatsApp.'; }));
    socket.ev.on('messages.update', updates => {
      if (currentGeneration !== generation) return;
      if (updates.map(({key, update}) => updateReceipt(ledger, key, update.status)).some(Boolean)) {
        persist().catch(() => { statusError = 'Falha ao salvar a confirmação de entrega.'; });
      }
    });
    socket.ev.on('connection.update', async update => {
      if (currentGeneration !== generation || shuttingDown) return;
      if (update.qr) {
        const image = await QRCode.toDataURL(update.qr, { width: 280, margin: 2 });
        if (currentGeneration === generation && state !== 'connected') { qr = image; state = 'qr'; }
      }
      if (update.connection === 'open') { state = 'connected'; qr = null; statusError = null; }
      if (update.connection === 'close') {
        qr = null;
        const code = update.lastDisconnect?.error?.output?.statusCode;
        state = 'disconnected';
        if (code === DisconnectReason.loggedOut) {
          statusError = 'Sessão encerrada no celular. Clique em Conectar para parear novamente.';
          // Archive the revoked auth folder; preserve it for troubleshooting.
          try { await rename(authDir, `${authDir}-revoked-${Date.now()}`); } catch {}
        } else {
          statusError = 'Conexão interrompida. Reconectando…';
          clearTimeout(reconnectTimer);
          reconnectTimer = setTimeout(() => connect().catch(() => {}), 5000);
        }
      }
    });
  } catch {
    state = 'disconnected'; statusError = 'Não foi possível conectar ao WhatsApp. Tente novamente.';
  } finally { connecting = false; }
}

function json(res, code, body) {
  res.writeHead(code, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(body));
}
async function readBody(req) {
  let body = '';
  for await (const chunk of req) {
    body += chunk;
    if (body.length > 8192) throw new Error('Corpo excede o limite.');
  }
  return body ? JSON.parse(body) : {};
}
function authorized(req) {
  const value = Buffer.from(req.headers.authorization || '');
  const expected = Buffer.from(`Bearer ${token}`);
  return value.length === expected.length && timingSafeEqual(value, expected);
}

async function resolveTarget(res, recipient, keyFor) {
  try {
    const jid = await resolveRecipient(socket, recipient);
    return { jid, key: await keyFor(jid) };
  } catch (error) {
    json(res, error.code === 'RECIPIENT_NOT_FOUND' ? 422 : 503, {
      error: error.code === 'RECIPIENT_NOT_FOUND' ? 'Número não encontrado no WhatsApp. Confira DDI e DDD.' : 'Consulta ao WhatsApp indisponível. Tente novamente.',
    });
    return null;
  }
}

// A ledger entry means this message already went out or may have: never send it twice.
function repeated(res, key) {
  if (ledger[key]?.state === 'sent') { json(res, 200, { message_id: ledger[key].message_id }); return true; }
  if (ledger[key]) { json(res, 409, { error: 'Envio já registrado ou em andamento.' }); return true; }
  return false;
}

async function sendOnce(res, { jid, key }, recipient, content) {
  // Earlier awaits yielded; check again right before reserving the key.
  if (repeated(res, key)) return;
  if (state !== 'connected' || !socket) return json(res, 503, { error: 'WhatsApp desconectado.' });
  const messageId = generateMessageIDV2(socket.user?.id);
  ledger[key] = { state: 'sending', recipient, resolved_jid: jid, message_id: messageId, at: Date.now() };
  await persist();
  try {
    const message = await socket.sendMessage(jid, content, { messageId });
    if (!message?.key?.id) throw new Error('Sem confirmação');
    ledger[key] = { ...ledger[key], state: 'sent', message_id: message.key.id, message: encodeMessage(message.message) };
    await persist();
    return json(res, 200, { message_id: message.key.id });
  } catch {
    ledger[key].state = 'uncertain'; await persist();
    return json(res, 409, { error: 'Envio sem confirmação. Confira o WhatsApp.' });
  }
}

const server = http.createServer(async (req, res) => {
  if (!authorized(req)) return json(res, 401, { error: 'Não autorizado.' });
  try {
    if (req.method === 'GET' && req.url === '/status') return json(res, 200, { state, qr, error: statusError });
    if (req.method === 'POST' && req.url === '/connect') {
      await connect(); return json(res, 200, { state, qr, error: statusError });
    }
    if (req.method === 'POST' && req.url === '/recipient') {
      const phone = validateRecipient((await readBody(req)).recipient);
      if (state !== 'connected' || !socket) return json(res, 503, { error: 'WhatsApp desconectado.' });
      const jid = await resolveRecipient(socket, phone);
      return json(res, 200, { exists: true, jid });
    }
    if (req.method === 'POST' && req.url === '/delivery') {
      const body = await readBody(req), id = validateClip(body);
      const phone = body.recipient ? validateRecipient(body.recipient) : undefined;
      const entries = receiptEntries(ledger, id, phone).map(([, entry]) => ({
        recipient: entry.recipient, state: entry.state, receipt: entry.receipt || 'unconfirmed', error: entry.receipt_error || null,
      }));
      return json(res, 200, entries.length === 1 ? entries[0] : { state: entries.length ? 'multiple' : 'unknown', deliveries: entries });
    }
    if (req.method === 'POST' && req.url === '/retry') {
      const body = await readBody(req), id = validateClip(body);
      const phone = body.recipient ? validateRecipient(body.recipient) : undefined;
      let entries = receiptEntries(ledger, id, phone);
      if (phone && !entries.length && state === 'connected' && socket) {
        const jid = await resolveRecipient(socket, phone);
        const key = await deliveryKey(ledger, id, phone, jid, number => resolveRecipient(socket, number));
        if (ledger[key]) entries = [[key, ledger[key]]];
      }
      if (!phone && entries.length > 1) return json(res, 400, { error: 'Informe o destinatário do reenvio.' });
      if (entries.some(([, entry]) => entry.state === 'sending')) return json(res, 409, { error: 'Envio em andamento.' });
      for (const [key, entry] of entries) if (entry.state !== 'sent') delete ledger[key];
      await persist();
      return json(res, 200, { ok: true });
    }
    if (req.method === 'POST' && req.url === '/send') {
      const body = validateSend(await readBody(req));
      if (state !== 'connected' || !socket) return json(res, 503, { error: 'WhatsApp desconectado.' });
      const target = await resolveTarget(res, body.recipient, jid => deliveryKey(ledger, body.clip_id, body.recipient, jid, phone => resolveRecipient(socket, phone)));
      if (!target) return;
      await persist(); // Save any legacy receipt migration before responding.
      if (repeated(res, target.key)) return;
      const file = await realpath(path.join(clips, `${body.clip_id}.mp4`));
      if (path.dirname(file) !== await realpath(clips)) return json(res, 400, { error: 'Arquivo inválido.' });
      if ((await stat(file)).size > 30 * 1024 * 1024) return json(res, 413, { error: 'Vídeo excede 30 MB. Reduza a duração dos segmentos.' });
      return sendOnce(res, target, body.recipient, { video: { url: file }, caption: body.caption, mimetype: 'video/mp4' });
    }
    if (req.method === 'POST' && req.url === '/text') {
      const body = validateText(await readBody(req));
      if (state !== 'connected' || !socket) return json(res, 503, { error: 'WhatsApp desconectado.' });
      const target = await resolveTarget(res, body.recipient, jid => `alert:${body.alert_id}:${jid}`);
      if (!target) return;
      return sendOnce(res, target, body.recipient, { text: body.text });
    }
    json(res, 404, { error: 'Rota não encontrada.' });
  } catch { json(res, 400, { error: 'Solicitação inválida ou arquivo indisponível.' }); }
});

server.listen(Number(process.env.WA_PORT || 3001), '127.0.0.1', () => console.log('Serviço WhatsApp disponível em localhost.'));
// Restore paired sessions, but do not request QR codes until the user clicks Connect.
try { await stat(path.join(authDir, 'creds.json')); await connect(); } catch {}
async function shutdown() {
  shuttingDown = true; clearTimeout(reconnectTimer);
  socket?.end(undefined);
  server.close();
  await saveChain.catch(() => {});
  process.exit(0);
}
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
