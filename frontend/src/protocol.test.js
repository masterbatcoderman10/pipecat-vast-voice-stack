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

test('handles realtime session and VAD events', () => {
  let state = initialState();
  state = reduceEvent(state, { type: 'session.ready' });
  assert.equal(state.status, 'listening');
  state = reduceEvent(state, { type: 'vad.speech_start' });
  assert.equal(state.status, 'user_speaking');
  state = reduceEvent(state, { type: 'vad.speech_stop' });
  assert.equal(state.status, 'transcribing');
});

test('handles realtime STT partial and final transcripts', () => {
  let state = { ...initialState(), transcript: 'previous final' };
  state = reduceEvent(state, { type: 'stt.partial', text: 'partial words' });
  assert.equal(state.interimTranscript, 'partial words');
  assert.equal(state.transcript, 'previous final');

  state = reduceEvent(state, { type: 'stt.final', text: 'final words' });
  assert.equal(state.transcript, 'final words');
  assert.equal(state.interimTranscript, '');
  assert.equal(state.status, 'thinking');
});

test('handles realtime LLM streaming and segments', () => {
  let state = { ...initialState(), assistantText: 'old answer' };
  state = reduceEvent(state, { type: 'llm.start' });
  assert.equal(state.status, 'thinking');
  assert.equal(state.assistantText, '');

  state = reduceEvent(state, { type: 'llm.token', text: 'hel' });
  state = reduceEvent(state, { type: 'llm.token', token: 'lo' });
  assert.equal(state.assistantText, 'hello');

  state = reduceEvent(state, { type: 'llm.segment', id: 'seg-1', text: 'hello', index: 0 });
  assert.deepEqual(state.segments, [{ id: 'seg-1', text: 'hello', index: 0 }]);
  assert.deepEqual(state.currentSegment, { id: 'seg-1', text: 'hello', index: 0 });

  state = reduceEvent(state, { type: 'llm.segment', id: 'seg-1', text: 'hello there', index: 0 });
  assert.deepEqual(state.segments, [{ id: 'seg-1', text: 'hello there', index: 0 }]);
});

test('handles realtime TTS audio lifecycle', () => {
  let state = initialState();
  state = reduceEvent(state, { type: 'tts.start', segment_id: 'seg-1' });
  assert.equal(state.status, 'speaking');
  assert.deepEqual(state.currentSegment, { id: 'seg-1' });

  state = reduceEvent(state, { type: 'tts.audio_start', segment_id: 'seg-1' });
  assert.equal(state.status, 'speaking');

  state = reduceEvent(state, { type: 'tts.audio_done', bytes: 42, elapsed_ms: 7, segment_id: 'seg-1' });
  assert.deepEqual(state.audio, { bytes: 42, elapsed_ms: 7, segment_id: 'seg-1' });
});

test('handles realtime response completion, cancellation, and errors', () => {
  let state = { ...initialState(), status: 'speaking', audio: { bytes: 42 }, currentSegment: { id: 'seg-1' } };
  state = reduceEvent(state, { type: 'response.done', timings: { total_ms: 12 } });
  assert.equal(state.status, 'done');
  assert.deepEqual(state.timings, { total_ms: 12 });

  state = { ...state, status: 'speaking', audio: { bytes: 42 }, currentSegment: { id: 'seg-1' } };
  state = reduceEvent(state, { type: 'response.cancelled' });
  assert.equal(state.status, 'idle');
  assert.equal(state.cancelled, true);
  assert.equal(state.audio, null);
  assert.equal(state.currentSegment, null);

  state = reduceEvent(state, { type: 'error', message: 'boom' });
  assert.equal(state.status, 'error');
  assert.equal(state.error, 'boom');
});
