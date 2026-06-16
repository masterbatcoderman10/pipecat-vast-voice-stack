import { useRef, useState } from 'react';
import { reduceEvent } from './protocol.js';

const wsUrl = import.meta.env.VITE_BACKEND_WS || 'ws://127.0.0.1:7860/v1/voice-turn/ws';
const initialState = () => ({ status: 'idle', transcript: '', assistantText: '', timings: null, audio: null, error: null });

export default function App() {
  const recorder = useRef(null);
  const chunks = useRef([]);
  const [state, setState] = useState(initialState);
  const [audioUrl, setAudioUrl] = useState(null);
  const [voice, setVoice] = useState('clone:sylens');

  async function start() {
    chunks.current = [];
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl(null);
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

  function stop() {
    if (!recorder.current || recorder.current.state !== 'recording') return;
    recorder.current.onstop = send;
    recorder.current.stop();
    recorder.current.stream.getTracks().forEach((track) => track.stop());
  }

  async function send() {
    setState((current) => ({ ...current, status: 'uploading' }));
    const mimeType = recorder.current?.mimeType || 'audio/webm';
    const blob = new Blob(chunks.current, { type: mimeType });
    const ws = new WebSocket(wsUrl);
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

  return (
    <main>
      <h1>Pipecat Voice Note</h1>
      <label>
        Voice
        <input value={voice} onChange={(event) => setVoice(event.target.value)} />
      </label>
      <p>Status: {state.status}</p>
      <p>Backend: <code>{wsUrl}</code></p>
      {state.status !== 'recording'
        ? <button onClick={start}>Record</button>
        : <button onClick={stop}>Stop + Send</button>}

      <h2>Transcript</h2>
      <p>{state.transcript || '—'}</p>

      <h2>Assistant</h2>
      <p>{state.assistantText || '—'}</p>

      {audioUrl && <audio controls autoPlay src={audioUrl} />}
      {state.timings && <pre>{JSON.stringify(state.timings, null, 2)}</pre>}
      {state.audio && <p>Audio: {state.audio.bytes} bytes in {state.audio.elapsed_ms} ms</p>}
      {state.error && <p className="error">{state.error}</p>}
    </main>
  );
}
