import test from 'node:test';
import assert from 'node:assert/strict';
import { reduceEvent } from './protocol.js';

const initialState = () => ({
  status: 'idle',
  assistantText: '',
  transcript: '',
  timings: null,
  audio: null,
  error: null,
});

test('accumulates token events', () => {
  let state = initialState();
  state = reduceEvent(state, { type: 'transcript', text: 'hi' });
  state = reduceEvent(state, { type: 'llm_token', text: 'hello' });
  state = reduceEvent(state, { type: 'llm_token', text: '!' });
  state = reduceEvent(state, { type: 'done', timings: { total_ms: 1 } });
  assert.equal(state.transcript, 'hi');
  assert.equal(state.assistantText, 'hello!');
  assert.equal(state.status, 'done');
  assert.deepEqual(state.timings, { total_ms: 1 });
});

test('tracks status and errors for websocket events', () => {
  let state = initialState();
  state = reduceEvent(state, { type: 'ready' });
  assert.equal(state.status, 'ready');
  state = reduceEvent(state, { type: 'stt_start' });
  assert.equal(state.status, 'transcribing');
  state = reduceEvent(state, { type: 'tts_start' });
  assert.equal(state.status, 'speaking');
  state = reduceEvent(state, { type: 'audio_start', mime_type: 'audio/wav' });
  assert.equal(state.status, 'receiving_audio');
  state = reduceEvent(state, { type: 'audio_done', bytes: 42, elapsed_ms: 7 });
  assert.deepEqual(state.audio, { bytes: 42, elapsed_ms: 7 });
  state = reduceEvent(state, { type: 'error', message: 'boom' });
  assert.equal(state.status, 'error');
  assert.equal(state.error, 'boom');
});

test('llm_done uses full text without duplicating accumulated tokens', () => {
  let state = initialState();
  state = reduceEvent(state, { type: 'llm_start' });
  state = reduceEvent(state, { type: 'llm_token', text: 'hel' });
  state = reduceEvent(state, { type: 'llm_done', text: 'hello' });
  assert.equal(state.assistantText, 'hello');
});
