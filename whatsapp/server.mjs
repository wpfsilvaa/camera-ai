import 'dotenv/config';
import http from 'node:http';
import { mkdir, readFile, writeFile, rename, stat, realpath } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomBytes, timingSafeEqual } from 'node:crypto';
import makeWASocket, { DisconnectReason, useMultiFileAuthState, makeCacheableSignalKeyStore, generateMessageIDV2 } from '@whiskeysockets/baileys';
import QRCode from 'qrcode';
import pino from 'pino';
import { validateSend, validateClip, validateRecipient } from './validation.mjs';
import { resolveRecipient, updateReceipt, savedMessage, encodeMessage } from './delivery.mjs';

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
      const id = validateClip(await readBody(req));
      const entry = ledger[id];
      return json(res, 200, entry ? { state: entry.state, receipt: entry.receipt || 'unconfirmed', error: entry.receipt_error || null } : { state: 'unknown' });
    }
    if (req.method === 'POST' && req.url === '/retry') {
      const id = validateClip(await readBody(req));
      if (ledger[id]?.state === 'sending') return json(res, 409, { error: 'Envio em andamento.' });
      // Keep successful receipts: retrying a timed out HTTP request must not duplicate a video.
      if (ledger[id]?.state !== 'sent') { delete ledger[id]; await persist(); }
      return json(res, 200, { ok: true });
    }
    if (req.method === 'POST' && req.url === '/send') {
      const body = validateSend(await readBody(req));
      const existing = ledger[body.clip_id];
      if (existing?.state === 'sent') return json(res, 200, { message_id: existing.message_id });
      if (existing) return json(res, 409, { error: 'Envio sem confirmação ou em andamento.' });
      if (state !== 'connected' || !socket) return json(res, 503, { error: 'WhatsApp desconectado.' });
      const file = await realpath(path.join(clips, `${body.clip_id}.mp4`));
      if (path.dirname(file) !== await realpath(clips)) return json(res, 400, { error: 'Arquivo inválido.' });
      if ((await stat(file)).size > 30 * 1024 * 1024) return json(res, 413, { error: 'Vídeo excede 30 MB. Reduza a duração dos segmentos.' });
      // Filesystem checks yielded; another request may have reserved this clip meanwhile.
      if (ledger[body.clip_id]?.state === 'sent') return json(res, 200, { message_id: ledger[body.clip_id].message_id });
      if (ledger[body.clip_id]) return json(res, 409, { error: 'Envio sem confirmação ou em andamento.' });
      if (state !== 'connected' || !socket) return json(res, 503, { error: 'WhatsApp desconectado.' });
      let jid;
      try { jid = await resolveRecipient(socket, body.recipient); }
      catch (error) {
        return error.code === 'RECIPIENT_NOT_FOUND'
          ? json(res, 422, { error: 'Número não encontrado no WhatsApp. Confira DDI e DDD.' })
          : json(res, 503, { error: 'Consulta ao WhatsApp indisponível. Tente novamente.' });
      }
      // Recipient lookup also yielded: reserve only once across concurrent requests.
      if (ledger[body.clip_id]?.state === 'sent') return json(res, 200, { message_id: ledger[body.clip_id].message_id });
      if (ledger[body.clip_id]) return json(res, 409, { error: 'Envio já registrado ou em andamento.' });
      const messageId = generateMessageIDV2(socket.user?.id);
      ledger[body.clip_id] = { state: 'sending', recipient: body.recipient, resolved_jid: jid, message_id: messageId, at: Date.now() };

      await persist();
      try {
        const message = await socket.sendMessage(jid, {
          video: { url: file }, caption: body.caption, mimetype: 'video/mp4',
        }, { messageId });
        if (!message?.key?.id) throw new Error('Sem confirmação');
        ledger[body.clip_id] = { ...ledger[body.clip_id], state: 'sent', message_id: message.key.id, message: encodeMessage(message.message) };
        await persist();
        return json(res, 200, { message_id: message.key.id });
      } catch {
        ledger[body.clip_id].state = 'uncertain'; await persist();
        return json(res, 409, { error: 'Envio sem confirmação. Confira o WhatsApp.' });
      }
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
