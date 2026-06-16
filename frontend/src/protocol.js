export function reduceEvent(state, event) {
  if (event.type === 'ready') return { ...state, status: 'ready' };
  if (event.type === 'stt_start') return { ...state, status: 'transcribing' };
  if (event.type === 'transcript') return { ...state, transcript: event.text || '', status: 'thinking' };
  if (event.type === 'llm_start') return { ...state, assistantText: '', status: 'thinking' };
  if (event.type === 'llm_token') return { ...state, assistantText: state.assistantText + (event.text || '') };
  if (event.type === 'llm_done') return { ...state, assistantText: event.text || state.assistantText };
  if (event.type === 'tts_start') return { ...state, status: 'speaking' };
  if (event.type === 'audio_start') return { ...state, status: 'receiving_audio' };
  if (event.type === 'audio_done') {
    return { ...state, audio: { bytes: event.bytes, elapsed_ms: event.elapsed_ms } };
  }
  if (event.type === 'done') return { ...state, status: 'done', timings: event.timings };
  if (event.type === 'error') return { ...state, status: 'error', error: event.message || 'unknown error' };
  return state;
}
