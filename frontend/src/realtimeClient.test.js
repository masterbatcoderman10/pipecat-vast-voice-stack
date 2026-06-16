import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildSessionStart,
  float32ToPcm16,
  nextRealtimeWsUrl,
  pcm16ToFloat32,
  PcmPlaybackQueue,
} from './realtimeClient.js';

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

test('pcm16ToFloat32 converts little-endian PCM chunks into normalized floats', () => {
  const buffer = new ArrayBuffer(8);
  const view = new DataView(buffer);
  view.setInt16(0, -32768, true);
  view.setInt16(2, -16384, true);
  view.setInt16(4, 0, true);
  view.setInt16(6, 32767, true);

  const floats = pcm16ToFloat32(buffer);
  assert.deepEqual(Array.from(floats).map((value) => Number(value.toFixed(3))), [-1, -0.5, 0, 1]);
});

test('PcmPlaybackQueue schedules raw PCM chunks using tts.audio_start metadata', () => {
  const scheduled = [];
  const context = {
    currentTime: 10,
    destination: {},
    createBuffer(channels, frameCount, sampleRate) {
      assert.equal(channels, 1);
      assert.equal(frameCount, 4);
      assert.equal(sampleRate, 24000);
      return {
        data: new Float32Array(frameCount),
        getChannelData() {
          return this.data;
        },
      };
    },
    createBufferSource() {
      const source = {
        buffer: null,
        connect(destination) { this.destination = destination; },
        start(when) { scheduled.push({ when, data: Array.from(this.buffer.data) }); },
      };
      return source;
    },
  };
  const queue = new PcmPlaybackQueue({ audioContext: context });
  queue.configure({ sample_rate: 24000, channels: 1, encoding: 'pcm_s16le' });

  const buffer = new ArrayBuffer(8);
  const view = new DataView(buffer);
  view.setInt16(0, 0, true);
  view.setInt16(2, 8192, true);
  view.setInt16(4, 16384, true);
  view.setInt16(6, 32767, true);

  queue.enqueue(buffer);
  assert.equal(scheduled.length, 1);
  assert.equal(scheduled[0].when, 10);
  assert.deepEqual(scheduled[0].data.map((value) => Number(value.toFixed(2))), [0, 0.25, 0.5, 1]);
  assert.equal(queue.nextStartTime > 10, true);
});

test('buildSessionStart returns default realtime session.start event', () => {
  const event = buildSessionStart({});
  assert.match(event.session_id, /.+/);
  assert.deepEqual({ ...event, session_id: '<present>' }, {
    type: 'session.start',
    session_id: '<present>',
    sample_rate: 16000,
    channels: 1,
    encoding: 'pcm_s16le',
    voice: 'clone:sylens',
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
