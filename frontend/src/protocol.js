const eventText = (event) => event.text ?? event.token ?? event.transcript ?? '';

function segmentFromEvent(event) {
  const id = event.id ?? event.segment_id;
  const segment = event.segment ?? {};
  return {
    ...(id === undefined ? {} : { id }),
    ...segment,
    ...(event.text === undefined ? {} : { text: event.text }),
    ...(event.index === undefined ? {} : { index: event.index }),
  };
}

function upsertSegment(segments = [], segment) {
  const index = segments.findIndex((item) => item.id !== undefined && item.id === segment.id);
  if (index === -1) return [...segments, segment];
  return segments.map((item, itemIndex) => (itemIndex === index ? { ...item, ...segment } : item));
}

export function reduceEvent(state, event) {
  if (event.type === 'ready') return { ...state, status: 'ready' };
  if (event.type === 'session.ready') return { ...state, status: 'listening', cancelled: false };
  if (event.type === 'vad.speech_start') return { ...state, status: 'user_speaking' };
  if (event.type === 'vad.speech_stop') return { ...state, status: 'transcribing' };

  if (event.type === 'stt_start') return { ...state, status: 'transcribing' };
  if (event.type === 'stt.partial') return { ...state, interimTranscript: eventText(event) };
  if (event.type === 'transcript') return { ...state, transcript: event.text || '', status: 'thinking' };
  if (event.type === 'stt.final') {
    return { ...state, transcript: eventText(event), interimTranscript: '', status: 'thinking' };
  }

  if (event.type === 'llm_start' || event.type === 'llm.start') {
    return { ...state, assistantText: '', status: 'thinking' };
  }
  if (event.type === 'llm_token' || event.type === 'llm.token') {
    return { ...state, assistantText: state.assistantText + eventText(event) };
  }
  if (event.type === 'llm.segment') {
    const segment = segmentFromEvent(event);
    return { ...state, segments: upsertSegment(state.segments, segment), currentSegment: segment };
  }
  if (event.type === 'llm_done') return { ...state, assistantText: event.text || state.assistantText };

  if (event.type === 'tts_start') return { ...state, status: 'speaking' };
  if (event.type === 'tts.start' || event.type === 'tts.audio_start') {
    const segment = segmentFromEvent(event);
    return {
      ...state,
      status: 'speaking',
      ...(Object.keys(segment).length === 0 ? {} : { currentSegment: segment }),
    };
  }
  if (event.type === 'audio_start') return { ...state, status: 'receiving_audio' };
  if (event.type === 'audio_done') {
    return { ...state, audio: { bytes: event.bytes, elapsed_ms: event.elapsed_ms } };
  }
  if (event.type === 'tts.audio_done') {
    return {
      ...state,
      audio: { bytes: event.bytes, elapsed_ms: event.elapsed_ms, segment_id: event.segment_id ?? event.id },
    };
  }

  if (event.type === 'done' || event.type === 'response.done') {
    return { ...state, status: 'done', timings: event.timings };
  }
  if (event.type === 'response.cancelled') {
    return { ...state, status: 'idle', cancelled: true, audio: null, currentSegment: null };
  }
  if (event.type === 'error') return { ...state, status: 'error', error: event.message || 'unknown error' };
  return state;
}
