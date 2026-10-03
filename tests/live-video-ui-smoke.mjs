// Light video (WebRTC from the camera computer) in a phone-sized browser. Needs the real camera computer:
// LIVE_CAMERA=rtsp://<notebook>:8554/cam node tests/live-video-ui-smoke.mjs
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp, mkdir, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';

await mkdir('test-results', {recursive: true});
const data = await mkdtemp(path.join(tmpdir(), 'live-video-ui-'));
const base = 'http://127.0.0.1:18041';
const server = spawn('.venv/bin/python', ['tests/live_video_ui_server.py', '18041'], {env: {...process.env, PYTHONPATH: '.', CAMERA_DATA_DIR: data, DASHBOARD_PASSWORD: '', WA_PORT: '18042', CUDA_VISIBLE_DEVICES: ''}, stdio: ['ignore', 'ignore', 'pipe']});
let logs = '', browser;
server.stderr.on('data', chunk => logs += chunk);
try {
  for (let i = 0; i < 200; i++) { try { if ((await fetch(base + '/api/settings')).ok) break; } catch {} if (i === 199) throw Error(logs); await new Promise(r => setTimeout(r, 200)); }
  browser = await chromium.launch({executablePath: process.env.CHROME_PATH || '/opt/google/chrome/chrome', headless: true, args: ['--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 390, height: 844}}), errors = [], intercom = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', r => { if (r.url().includes('/api/intercom/')) intercom.push(r.url().split('/api/intercom/')[1]); });
  await page.goto(base);

  // Phones start in light mode: WebRTC video at 640 px, no MJPEG.
  await page.waitForFunction(() => document.querySelector('#live-video').videoWidth === 640, null, {timeout: 30000});
  assert.equal(await page.locator('[data-view="direct"]').getAttribute('aria-pressed'), 'true');
  assert.equal(await page.locator('#live-image').getAttribute('src'), null);
  assert.equal(await page.locator('#camera-placeholder').isHidden(), true);
  await page.waitForTimeout(1500);
  const frames = await page.evaluate(() => document.querySelector('#live-video').getVideoPlaybackQuality().totalVideoFrames);
  assert.ok(frames > 10, `poucos quadros: ${frames}`);
  await page.locator('.live-panel').screenshot({path: 'test-results/live-video-mobile.png'});

  // "Com detecções" switches to the server MJPEG and hangs up the WebRTC session; the choice is remembered.
  await page.locator('[data-view="boxes"]').click();
  await page.waitForFunction(() => document.querySelector('#live-image').naturalWidth > 0, null, {timeout: 20000});
  assert.equal(await page.locator('#live-video').isHidden(), true);
  assert.ok(intercom.includes('hangup'));
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#live-image').naturalWidth > 0, null, {timeout: 20000});
  assert.equal(await page.locator('[data-view="boxes"]').getAttribute('aria-pressed'), 'true');

  // Back to light mode; leaving the overview stops the video (no data used in the background).
  await page.locator('[data-view="direct"]').click();
  await page.waitForFunction(() => document.querySelector('#live-video').videoWidth === 640, null, {timeout: 30000});
  const hangups = intercom.filter(k => k === 'hangup').length;
  await page.locator('a[data-page="history"]').click();
  await page.waitForTimeout(500);
  assert.equal(intercom.filter(k => k === 'hangup').length, hangups + 1);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
  assert.deepEqual(errors, []);
  console.log(`Vídeo leve: 640 px no celular, ${frames} quadros em ~2 s, troca para detecções, preferência lembrada e parada fora da visão geral OK.`);
} finally {
  await browser?.close();
  server.kill();
  await rm(data, {recursive: true, force: true});
}
