import { useRef, useState } from 'react';
import { reduceEvent } from './protocol.js';
import { createAudioWorkletStreamer, nextRealtimeWsUrl, PcmPlaybackQueue, RealtimeVoiceClient } from './realtimeClient.js';

const legacyWsUrl = import.meta.env.VITE_BACKEND_WS || 'ws://127.0.0.1:7860/v1/voice-turn/ws';
const realtimeWsUrl = nextRealtimeWsUrl(import.meta.env.VITE_BACKEND_WS);
const initialState = () => ({
  status: 'idle',
  transcript: '',
  interimTranscript: '',
  assistantText: '',
  segments: [],
  currentSegment: null,
  timings: null,
  audio: null,
  error: null,
});

export default function App() {
  const recorder = useRef(null);
  const chunks = useRef([]);
  const realtimeClient = useRef(null);
  const realtimeStream = useRef(null);
  const realtimeStreamer = useRef(null);
  const realtimeAudioContext = useRef(null);
  const realtimePlayback = useRef(null);
  const [state, setState] = useState(initialState);
  const [audioUrl, setAudioUrl] = useState(null);
  const [realtimeAudioUrls, setRealtimeAudioUrls] = useState([]);
  const [voice, setVoice] = useState('clone:sylens');
  const [mode, setMode] = useState('realtime');

  function resetAudio() {
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    realtimeAudioUrls.forEach((url) => URL.revokeObjectURL(url));
    realtimePlayback.current?.stop();
    realtimePlayback.current = null;
    realtimeAudioContext.current?.close?.();
    realtimeAudioContext.current = null;
    setAudioUrl(null);
    setRealtimeAudioUrls([]);
  }

  async function start() {
    if (mode === 'legacy') return startLegacy();
    return startRealtime();
  }

  function stop() {
    if (mode === 'legacy') return stopLegacy();
    return stopRealtime();
  }

  async function startRealtime() {
    resetAudio();
    setState({ ...initialState(), status: 'connecting' });

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
      const audioContext = new AudioContextCtor({ sampleRate: 16000 });
      const client = new RealtimeVoiceClient({
        url: realtimeWsUrl,
        voice,
        onEvent: (event) => {
          if (event.type === 'tts.audio_start' && event.encoding === 'pcm_s16le') {
            realtimePlayback.current?.configure(event);
          }
          setState((current) => reduceEvent(current, event));
          if (event.type === 'response.done' || event.type === 'error') {
            cleanupRealtimeInput();
            if (event.type === 'error') realtimeClient.current?.close();
          }
        },
        onAudio: (data) => {
          realtimePlayback.current?.enqueue(data);
        },
        onError: () => {
          setState((current) => ({ ...current, status: 'error', error: 'websocket failed' }));
        },
      });

      realtimeStream.current = stream;
      realtimeAudioContext.current = audioContext;
      realtimePlayback.current = new PcmPlaybackQueue({ audioContext, sampleRate: 24000, channels: 1 });
      realtimeClient.current = client;
      await client.connect();
      realtimeStreamer.current = await createAudioWorkletStreamer({
        audioContext,
        stream,
        onChunk: (chunk) => client.sendPcmChunk(chunk),
      });
      setState((current) => ({ ...current, status: current.status === 'connecting' ? 'listening' : current.status }));
    } catch (error) {
      cleanupRealtimeInput();
      realtimeClient.current?.close();
      setState((current) => ({ ...current, status: 'error', error: error.message || 'microphone permission failed' }));
    }
  }

  function stopRealtime() {
    cleanupRealtimeInput();
    realtimeClient.current?.commit();
    setState((current) => ({ ...current, status: 'transcribing' }));
  }

  function cancelRealtime() {
    cleanupRealtimeInput();
    realtimePlayback.current?.stop();
    realtimeClient.current?.cancel();
    realtimeClient.current?.close();
    setState((current) => reduceEvent(current, { type: 'response.cancelled' }));
  }

  function cleanupRealtimeInput() {
    realtimeStreamer.current?.stop();
    realtimeStreamer.current = null;
    realtimeStream.current?.getTracks().forEach((track) => track.stop());
    realtimeStream.current = null;
  }

  async function startLegacy() {
    chunks.current = [];
    resetAudio();
    setState({ ...initialState(), status: 'recording' });
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recorder.current = new MediaRecorder(stream);
      recorder.current.ondataavailable = (event) => {
        if (event.data.size) chunks.current.push(event.data);
      };
      recorder.current.start();
    } catch (error) {
      setState((current) => ({ ...current, status: 'error', error: error.message || 'microphone permission failed' }));
    }
  }

  function stopLegacy() {
    if (!recorder.current || recorder.current.state !== 'recording') return;
    recorder.current.onstop = sendLegacy;
    recorder.current.stop();
    recorder.current.stream.getTracks().forEach((track) => track.stop());
  }

  async function sendLegacy() {
    setState((current) => ({ ...current, status: 'uploading' }));
    const mimeType = recorder.current?.mimeType || 'audio/webm';
    const blob = new Blob(chunks.current, { type: mimeType });
    const ws = new WebSocket(legacyWsUrl);
    ws.binaryType = 'arraybuffer';

    ws.onopen = async () => {
      ws.send(JSON.stringify({
        type: 'start',
        filename: 'recording.webm',
        mime_type: blob.type,
        voice,
        prompt_preamble: 'Reply briefly and conversationally.',
        session_id: crypto.randomUUID?.() || String(Date.now()),
      }));
      ws.send(await blob.arrayBuffer());
      ws.send(JSON.stringify({ type: 'end' }));
    };

    ws.onmessage = (message) => {
      if (typeof message.data === 'string') {
        const event = JSON.parse(message.data);
        setState((current) => reduceEvent(current, event));
        if (event.type === 'done' || event.type === 'error') ws.close();
        return;
      }

      const wav = new Blob([message.data], { type: 'audio/wav' });
      setAudioUrl((current) => {
        if (current) URL.revokeObjectURL(current);
        return URL.createObjectURL(wav);
      });
    };

    ws.onerror = () => {
      setState((current) => ({ ...current, status: 'error', error: 'websocket failed' }));
    };
  }

  const isRecording = state.status === 'recording' || state.status === 'listening' || state.status === 'user_speaking';

  return (
    <main>
      <h1>Pipecat Voice Note</h1>
      <label>
        Mode
        <select value={mode} onChange={(event) => setMode(event.target.value)} disabled={isRecording}>
          <option value="realtime">Realtime</option>
          <option value="legacy">Legacy full-turn</option>
        </select>
      </label>
      <label>
        Voice
        <input value={voice} onChange={(event) => setVoice(event.target.value)} />
      </label>
      <p>Status: {state.status}</p>
      <p>Backend: <code>{mode === 'realtime' ? realtimeWsUrl : legacyWsUrl}</code></p>
      {!isRecording
        ? <button onClick={start}>{mode === 'realtime' ? 'Start realtime' : 'Record'}</button>
        : <button onClick={stop}>{mode === 'realtime' ? 'Commit turn' : 'Stop + Send'}</button>}
      {mode === 'realtime' && isRecording && <button onClick={cancelRealtime}>Cancel</button>}

      <h2>Transcript</h2>
      <p>{state.transcript || '—'}</p>
      {state.interimTranscript && <p>Interim: {state.interimTranscript}</p>}

      <h2>Assistant</h2>
      <p>{state.assistantText || '—'}</p>
      {state.currentSegment && <p>Current segment: {state.currentSegment.text || state.currentSegment.id || '—'}</p>}
      {state.segments?.length > 0 && (
        <ul>
          {state.segments.map((segment, index) => (
            <li key={segment.id ?? index}>{segment.text || JSON.stringify(segment)}</li>
          ))}
        </ul>
      )}

      {audioUrl && <audio controls autoPlay src={audioUrl} />}
      {realtimeAudioUrls.map((url, index) => (
        <audio key={url} controls autoPlay={index === realtimeAudioUrls.length - 1} src={url} />
      ))}
      {state.timings && <pre>{JSON.stringify(state.timings, null, 2)}</pre>}
      {state.audio && <p>Audio: {state.audio.bytes} bytes in {state.audio.elapsed_ms ?? '—'} ms</p>}
      {state.error && <p className="error">{state.error}</p>}
    </main>
  );
}
