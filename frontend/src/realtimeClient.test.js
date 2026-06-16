import test from 'node:test';
import assert from 'node:assert/strict';
import { buildSessionStart, float32ToPcm16, nextRealtimeWsUrl } from './realtimeClient.js';

test('float32ToPcm16 clamps samples and returns little-endian int16 PCM', () => {
  const pcm = float32ToPcm16(new Float32Array([-2, -1, -0.5, 0, 0.5, 1, 2]));
  assert.ok(pcm instanceof ArrayBuffer);

  const view = new DataView(pcm);
  assert.equal(view.byteLength, 14);
  assert.equal(view.getInt16(0, true), -32768);
  assert.equal(view.getInt16(2, true), -32768);
  assert.equal(view.getInt16(4, true), -16384);
  assert.equal(view.getInt16(6, true), 0);
  assert.equal(view.getInt16(8, true), 16384);
  assert.equal(view.getInt16(10, true), 32767);
  assert.equal(view.getInt16(12, true), 32767);
});

test('buildSessionStart returns default realtime session.start event', () => {
  const event = buildSessionStart({});
  assert.match(event.session_id, /.+/);
  assert.deepEqual({ ...event, session_id: '<present>' }, {
    type: 'session.start',
    sample_rate: 16000,
    channels: 1,
    encoding: 'pcm_s16le',
    voice: 'clone:sylens',
    session_id: '<present>',
  });
});

test('buildSessionStart accepts voice override', () => {
  const event = buildSessionStart({ voice: 'clone:other' });
  assert.equal(event.voice, 'clone:other');
});

test('nextRealtimeWsUrl maps legacy, preserves v2, and defaults when undefined', () => {
  assert.equal(
    nextRealtimeWsUrl('ws://127.0.0.1:7860/v1/voice-turn/ws'),
    'ws://127.0.0.1:7860/v2/realtime/ws',
  );
  assert.equal(
    nextRealtimeWsUrl('wss://example.test/v1/voice-turn/ws?x=1'),
    'wss://example.test/v2/realtime/ws?x=1',
  );
  assert.equal(
    nextRealtimeWsUrl('ws://127.0.0.1:7860/v2/realtime/ws'),
    'ws://127.0.0.1:7860/v2/realtime/ws',
  );
  assert.equal(nextRealtimeWsUrl(undefined), 'ws://127.0.0.1:7860/v2/realtime/ws');
});
