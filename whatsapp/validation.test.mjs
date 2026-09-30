import test from 'node:test';
import assert from 'node:assert/strict';
import { validateSend, validateClip, validateText } from './validation.mjs';

test('accepts only local clip IDs and individual phone numbers', () => {
  const valid = { clip_id: 'a'.repeat(32), recipient: '5511999999999', caption: 'Presença na cozinha' };
  assert.deepEqual(validateSend(valid), valid);
  for (const clip_id of ['../../private', 'https://example.com/video.mp4', 'a'.repeat(31)]) {
    assert.throws(() => validateSend({ ...valid, clip_id }));
  }
  for (const recipient of ['5511999999999@g.us', '+5511999999999', 'abc', '123']) {
    assert.throws(() => validateSend({ ...valid, recipient }));
  }
  assert.throws(() => validateSend({ ...valid, caption: 'x'.repeat(1001) }));
  assert.throws(() => validateClip({ clip_id: '../secret' }));
});

test('accepts only short text alerts with a safe id', () => {
  const valid = { alert_id: 'inactive-1759000000', recipient: '5511999999999', text: 'Sem movimento há 4 horas.' };
  assert.deepEqual(validateText(valid), valid);
  for (const alert_id of ['../x', 'short', 'A'.repeat(20), 'a'.repeat(81)]) assert.throws(() => validateText({ ...valid, alert_id }));
  for (const text of ['', '   ', 'x'.repeat(1501), 42]) assert.throws(() => validateText({ ...valid, text }));
});
