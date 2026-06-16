# Streaming Token Voice + Local React Frontend Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. Use `ponytail` full mode and `software-development/tdd`: shortest working path, test first, no speculative abstractions.

**Goal:** Add a local browser UI that records a voice note, sends it to the Vast backend, and receives streaming LLM tokens plus playable response audio from the backend.

**Architecture:** Start with the smallest real streaming contract: a single FastAPI WebSocket endpoint. The browser sends one complete recorded audio blob; the backend emits JSON progress events, streams LLM tokens as they arrive, then sends one final TTS WAV. This gives token-level capability without pretending OmniVoice or Nemotron are realtime chunk-streaming yet.

**Tech Stack:** FastAPI WebSocket, existing `httpx` clients, vLLM OpenAI-compatible streaming, OmniVoice HTTP TTS, React + Vite + browser `MediaRecorder` + native WebSocket.

---

## Ponytail scope decision

Do **not** build WebRTC, TURN, Pipecat transports, audio jitter buffers, incremental STT, or barge-in in the first implementation. The current stack already proves full-turn voice notes. The next smallest useful step is:

```text
browser records complete clip
-> websocket sends clip
-> backend transcribes clip
-> backend streams LLM token events
-> backend synthesizes final audio once text is complete
-> browser plays final WAV
```

This is honestly token-level streaming, not realtime phone-call streaming. Add chunked mic/STT and barge-in only after this contract is green.

## Current baseline

Existing backend files:

- `app/main.py`
  - `POST /v1/voice-turn` returns JSON or final WAV after full pipeline.
  - `POST /v1/chat/completions` is non-streaming.
  - `POST /v1/audio/speech` returns final WAV.
- `app/pipeline.py`
  - `VoicePipeline.run_turn()` is sequential: normalize -> STT -> LLM -> TTS.
- `app/services/brain_client.py`
  - `BrainClient.complete()` calls vLLM with `stream: false`.
- `app/services/tts_client.py`
  - `TtsClient.synthesize()` calls OmniVoice and returns final WAV.
- `tests/test_api_contract.py`
  - Existing mock tests for full-turn behavior.

Validated runtime services:

- Main FastAPI: `7860`
- Nemotron STT adapter: `9001`
- vLLM/LiquidAI brain: `9002`
- `omnivoice-server`: `9003`

## Streaming contract v1

### Endpoint

```text
WS /v1/voice-turn/ws
```

### Client -> server messages

Use two message types only.

1. JSON config message, sent first:

```json
{
  "type": "start",
  "filename": "recording.webm",
  "mime_type": "audio/webm",
  "voice": "clone:sylens",
  "prompt_preamble": "Reply briefly and conversationally.",
  "session_id": "optional-browser-generated-id"
}
```

2. Binary audio message, sent second:

```text
<raw bytes from MediaRecorder blob>
```

Then client sends JSON end marker:

```json
{"type":"end"}
```

### Server -> client events

All server events are JSON text frames except final audio, which is binary.

```json
{"type":"ready"}
{"type":"stt_start"}
{"type":"transcript","text":"Hi, this is an audio sample. How are you doing?","elapsed_ms":1234}
{"type":"llm_start"}
{"type":"llm_token","text":"I"}
{"type":"llm_token","text":"'m"}
{"type":"llm_done","text":"I'm doing great, thanks for sending the audio sample!","first_token_ms":456,"total_ms":1800}
{"type":"tts_start"}
{"type":"audio_start","mime_type":"audio/wav"}
<binary WAV bytes>
{"type":"audio_done","bytes":134924,"elapsed_ms":3200}
{"type":"done","timings":{"stt_ms":1234,"llm_first_token_ms":456,"llm_total_ms":1800,"tts_total_ms":3200,"total_ms":6234}}
```

Error event:

```json
{"type":"error","message":"human readable error"}
```

### Acceptance criteria

- In mock mode, WebSocket returns deterministic events and valid WAV bytes without GPU services.
- In real mode, backend streams `llm_token` events from vLLM as they arrive.
- Frontend shows transcript, live assistant text, status, and plays final audio.
- Frontend runs locally on the Mac; backend remains on Vast or local mock server.
- No extra state store, auth, WebRTC, or streaming audio decoder in v1.

---

## Task 1: Add streaming brain client test

**Objective:** Lock the vLLM streaming parsing behavior before implementation.

**Files:**

- Modify: `tests/test_brain_streaming.py` (create)
- Modify later: `app/services/brain_client.py`

**Step 1: Write failing test**

Create `tests/test_brain_streaming.py`:

```python
import pytest

from app.config import Settings
from app.services.brain_client import BrainClient


@pytest.mark.asyncio
async def test_mock_stream_tokens():
    client = BrainClient(Settings(mock_mode=True))
    tokens = []
    async for token in client.stream_complete("hello"):
        tokens.append(token)
    assert "".join(tokens) == "Mock voice response to: hello"
    assert len(tokens) > 1
```

**Step 2: Run test to verify failure**

```bash
. .venv/bin/activate
pytest tests/test_brain_streaming.py -q
```

Expected: FAIL — `BrainClient` has no `stream_complete`.

**Step 3: Implement minimum mock stream**

In `app/services/brain_client.py`, add:

```python
from collections.abc import AsyncIterator
```

Add method:

```python
    async def stream_complete(self, transcript: str, prompt_preamble: Optional[str] = None) -> AsyncIterator[str]:
        if self.settings.mock_mode:
            text = f"Mock voice response to: {transcript}"
            for part in text.split(" "):
                yield part + " "
            return
        result = await self.complete(transcript, prompt_preamble=prompt_preamble)
        yield result.text
```

**Step 4: Run test**

```bash
pytest tests/test_brain_streaming.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/services/brain_client.py tests/test_brain_streaming.py
git commit -m "feat: add brain token stream contract"
```

---

## Task 2: Parse real vLLM SSE streaming

**Objective:** Make `BrainClient.stream_complete()` consume OpenAI-compatible streaming chunks from vLLM.

**Files:**

- Modify: `tests/test_brain_streaming.py`
- Modify: `app/services/brain_client.py`

**Step 1: Write failing unit test for SSE parser**

Add a tiny pure parser function so the streaming format can be tested without a server:

```python
def test_parse_openai_stream_delta():
    from app.services.brain_client import token_from_openai_sse_line

    line = 'data: {"choices":[{"delta":{"content":"hello"}}]}'
    assert token_from_openai_sse_line(line) == "hello"
    assert token_from_openai_sse_line("data: [DONE]") is None
    assert token_from_openai_sse_line("") is None
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_brain_streaming.py -q
```

Expected: FAIL — parser missing.

**Step 3: Implement parser and real streaming**

In `app/services/brain_client.py`:

```python
import json


def token_from_openai_sse_line(line: str) -> Optional[str]:
    if not line.startswith("data: "):
        return None
    data = line[6:].strip()
    if not data or data == "[DONE]":
        return None
    payload = json.loads(data)
    return payload.get("choices", [{}])[0].get("delta", {}).get("content")
```

Replace the non-mock fallback inside `stream_complete()` with real streaming:

```python
        messages = []
        if prompt_preamble:
            messages.append({"role": "system", "content": prompt_preamble})
        messages.append({"role": "user", "content": transcript})
        payload = {"model": self.settings.brain_served_model, "messages": messages, "stream": True}
        async with httpx.AsyncClient(timeout=self.settings.request_timeout_s) as client:
            async with client.stream("POST", f"{self.settings.brain_url}/v1/chat/completions", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    token = token_from_openai_sse_line(line)
                    if token:
                        yield token
```

**Step 4: Run tests**

```bash
pytest tests/test_brain_streaming.py tests/test_api_contract.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/services/brain_client.py tests/test_brain_streaming.py
git commit -m "feat: stream vllm chat tokens"
```

---

## Task 3: Add WebSocket mock contract test

**Objective:** Define the browser/backend event protocol in tests before adding the endpoint.

**Files:**

- Modify: `tests/test_ws_voice_turn.py` (create)
- Modify later: `app/main.py`

**Step 1: Write failing test**

Create `tests/test_ws_voice_turn.py`:

```python
import importlib
import json

from fastapi.testclient import TestClient

from app.utils.audio import validate_wav_bytes


def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_MODE", "1")
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    import app.main as main
    importlib.reload(main)
    return TestClient(main.app)


def test_voice_turn_websocket_contract(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    wav = open("tests/fixtures/sample.wav", "rb").read()

    with client.websocket_connect("/v1/voice-turn/ws") as ws:
        ws.send_text(json.dumps({"type": "start", "filename": "sample.wav", "voice": "default"}))
        assert ws.receive_json()["type"] == "ready"
        ws.send_bytes(wav)
        ws.send_text(json.dumps({"type": "end"}))

        seen = []
        audio = None
        while True:
            msg = ws.receive()
            if "text" in msg:
                event = json.loads(msg["text"])
                seen.append(event["type"])
                if event["type"] == "done":
                    break
            elif "bytes" in msg:
                audio = msg["bytes"]

    assert "transcript" in seen
    assert "llm_token" in seen
    assert "llm_done" in seen
    assert "audio_start" in seen
    assert "audio_done" in seen
    assert audio is not None
    validate_wav_bytes(audio)
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_ws_voice_turn.py -q
```

Expected: FAIL — route missing.

---

## Task 4: Implement `/v1/voice-turn/ws`

**Objective:** Add the minimal WebSocket endpoint matching the contract.

**Files:**

- Modify: `app/main.py`
- Test: `tests/test_ws_voice_turn.py`

**Step 1: Add imports**

In `app/main.py`:

```python
import json
import time
from fastapi import WebSocket, WebSocketDisconnect
```

**Step 2: Add endpoint**

Add below existing routes:

```python
@app.websocket("/v1/voice-turn/ws")
async def voice_turn_ws(websocket: WebSocket):
    await websocket.accept()
    total_start = time.perf_counter()
    try:
        start = json.loads(await websocket.receive_text())
        if start.get("type") != "start":
            await websocket.send_json({"type": "error", "message": "first message must be start"})
            return
        await websocket.send_json({"type": "ready"})

        audio = await websocket.receive_bytes()
        end = json.loads(await websocket.receive_text())
        if end.get("type") != "end":
            await websocket.send_json({"type": "error", "message": "expected end after audio bytes"})
            return

        await websocket.send_json({"type": "stt_start"})
        stt_start = time.perf_counter()
        normalized = normalize_wav_bytes(audio)
        stt_result = await pipeline.stt.transcribe(normalized, filename=start.get("filename") or "input.wav")
        stt_ms = int((time.perf_counter() - stt_start) * 1000)
        await websocket.send_json({"type": "transcript", "text": stt_result.text, "elapsed_ms": stt_ms})

        await websocket.send_json({"type": "llm_start"})
        llm_start = time.perf_counter()
        first_token_ms = None
        chunks = []
        async for token in pipeline.brain.stream_complete(stt_result.text, prompt_preamble=start.get("prompt_preamble")):
            if first_token_ms is None:
                first_token_ms = int((time.perf_counter() - llm_start) * 1000)
            chunks.append(token)
            await websocket.send_json({"type": "llm_token", "text": token})
        assistant_text = "".join(chunks).strip()
        llm_total_ms = int((time.perf_counter() - llm_start) * 1000)
        await websocket.send_json({"type": "llm_done", "text": assistant_text, "first_token_ms": first_token_ms or llm_total_ms, "total_ms": llm_total_ms})

        await websocket.send_json({"type": "tts_start"})
        tts_result = await pipeline.tts.synthesize(assistant_text, voice=start.get("voice"))
        await websocket.send_json({"type": "audio_start", "mime_type": "audio/wav"})
        await websocket.send_bytes(tts_result.audio)
        await websocket.send_json({"type": "audio_done", "bytes": len(tts_result.audio), "elapsed_ms": tts_result.total_ms})

        await websocket.send_json({
            "type": "done",
            "timings": {
                "stt_ms": stt_ms,
                "llm_first_token_ms": first_token_ms or llm_total_ms,
                "llm_total_ms": llm_total_ms,
                "tts_total_ms": tts_result.total_ms,
                "total_ms": int((time.perf_counter() - total_start) * 1000),
            },
        })
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
```

Also import `normalize_wav_bytes` from `app.utils.audio`.

**Step 3: Run WebSocket test**

```bash
pytest tests/test_ws_voice_turn.py -q
```

Expected: PASS.

**Step 4: Run backend tests**

```bash
pytest -q
```

Expected: all pass.

**Step 5: Commit**

```bash
git add app/main.py tests/test_ws_voice_turn.py
git commit -m "feat: add voice turn websocket"
```

Skipped: chunked binary frames. Add when browser `MediaRecorder` full-blob latency is the bottleneck.

---

## Task 5: Add tiny local React app scaffold

**Objective:** Add a frontend that runs locally and talks to the backend WebSocket URL.

**Files:**

- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/src/App.jsx`
- Create: `frontend/src/main.jsx`
- Create: `frontend/src/style.css`
- Create: `frontend/.env.example`

**Step 1: Create minimal Vite config through package scripts only**

`frontend/package.json`:

```json
{
  "scripts": {
    "dev": "vite --host 127.0.0.1 --port 5173",
    "build": "vite build",
    "test": "node --test src/protocol.test.js"
  },
  "dependencies": {
    "@vitejs/plugin-react": "latest",
    "vite": "latest",
    "react": "latest",
    "react-dom": "latest"
  },
  "devDependencies": {}
}
```

`frontend/.env.example`:

```bash
VITE_BACKEND_WS=ws://127.0.0.1:7860/v1/voice-turn/ws
```

**Step 2: Create app entry**

`frontend/index.html`:

```html
<div id="root"></div><script type="module" src="/src/main.jsx"></script>
```

`frontend/src/main.jsx`:

```jsx
import React from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import App from './App.jsx';

createRoot(document.getElementById('root')).render(<App />);
```

**Step 3: Commit scaffold**

```bash
git add frontend/
git commit -m "feat: add local react frontend scaffold"
```

---

## Task 6: Add frontend protocol helper with tests

**Objective:** Test the browser event reducer before UI wiring.

**Files:**

- Create: `frontend/src/protocol.js`
- Create: `frontend/src/protocol.test.js`

**Step 1: Write failing test**

`frontend/src/protocol.test.js`:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { reduceEvent } from './protocol.js';

test('accumulates token events', () => {
  let state = { status: 'idle', assistantText: '', transcript: '', timings: null };
  state = reduceEvent(state, { type: 'transcript', text: 'hi' });
  state = reduceEvent(state, { type: 'llm_token', text: 'hello' });
  state = reduceEvent(state, { type: 'llm_token', text: '!' });
  state = reduceEvent(state, { type: 'done', timings: { total_ms: 1 } });
  assert.equal(state.transcript, 'hi');
  assert.equal(state.assistantText, 'hello!');
  assert.equal(state.status, 'done');
  assert.deepEqual(state.timings, { total_ms: 1 });
});
```

**Step 2: Implement reducer**

`frontend/src/protocol.js`:

```js
export function reduceEvent(state, event) {
  if (event.type === 'transcript') return { ...state, transcript: event.text, status: 'thinking' };
  if (event.type === 'llm_start') return { ...state, assistantText: '', status: 'thinking' };
  if (event.type === 'llm_token') return { ...state, assistantText: state.assistantText + event.text };
  if (event.type === 'llm_done') return { ...state, assistantText: event.text || state.assistantText };
  if (event.type === 'tts_start') return { ...state, status: 'speaking' };
  if (event.type === 'done') return { ...state, status: 'done', timings: event.timings };
  if (event.type === 'error') return { ...state, status: 'error', error: event.message };
  return state;
}
```

**Step 3: Run test**

```bash
cd frontend
npm install
npm test
```

Expected: PASS.

**Step 4: Commit**

```bash
git add frontend/src/protocol.js frontend/src/protocol.test.js frontend/package-lock.json
git commit -m "feat: add frontend websocket event reducer"
```

---

## Task 7: Implement recording + WebSocket UI

**Objective:** Browser can record, send, show tokens, receive audio, and play it.

**Files:**

- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/style.css`

**Step 1: Implement simple app**

`frontend/src/App.jsx`:

```jsx
import { useRef, useState } from 'react';
import { reduceEvent } from './protocol.js';

const wsUrl = import.meta.env.VITE_BACKEND_WS || 'ws://127.0.0.1:7860/v1/voice-turn/ws';

export default function App() {
  const recorder = useRef(null);
  const chunks = useRef([]);
  const [state, setState] = useState({ status: 'idle', transcript: '', assistantText: '', timings: null });
  const [audioUrl, setAudioUrl] = useState(null);
  const [voice, setVoice] = useState('clone:sylens');

  async function start() {
    chunks.current = [];
    setAudioUrl(null);
    setState({ status: 'recording', transcript: '', assistantText: '', timings: null });
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recorder.current = new MediaRecorder(stream);
    recorder.current.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
    recorder.current.start();
  }

  function stop() {
    recorder.current.onstop = send;
    recorder.current.stop();
    recorder.current.stream.getTracks().forEach((t) => t.stop());
  }

  async function send() {
    setState((s) => ({ ...s, status: 'uploading' }));
    const blob = new Blob(chunks.current, { type: recorder.current.mimeType || 'audio/webm' });
    const ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';
    ws.onopen = async () => {
      ws.send(JSON.stringify({ type: 'start', filename: 'recording.webm', mime_type: blob.type, voice }));
      ws.send(await blob.arrayBuffer());
      ws.send(JSON.stringify({ type: 'end' }));
    };
    ws.onmessage = (msg) => {
      if (typeof msg.data === 'string') {
        const event = JSON.parse(msg.data);
        setState((s) => reduceEvent(s, event));
        if (event.type === 'done' || event.type === 'error') ws.close();
        return;
      }
      const wav = new Blob([msg.data], { type: 'audio/wav' });
      setAudioUrl(URL.createObjectURL(wav));
    };
    ws.onerror = () => setState((s) => ({ ...s, status: 'error', error: 'websocket failed' }));
  }

  return <main>
    <h1>Pipecat Voice Note</h1>
    <label>Voice <input value={voice} onChange={(e) => setVoice(e.target.value)} /></label>
    <p>Status: {state.status}</p>
    {state.status !== 'recording'
      ? <button onClick={start}>Record</button>
      : <button onClick={stop}>Stop + Send</button>}
    <h2>Transcript</h2><p>{state.transcript || '—'}</p>
    <h2>Assistant</h2><p>{state.assistantText || '—'}</p>
    {audioUrl && <audio controls autoPlay src={audioUrl} />}
    {state.timings && <pre>{JSON.stringify(state.timings, null, 2)}</pre>}
    {state.error && <p className="error">{state.error}</p>}
  </main>;
}
```

**Step 2: Add tiny CSS**

`frontend/src/style.css`:

```css
body { font-family: system-ui, sans-serif; margin: 2rem; background: #111; color: #eee; }
main { max-width: 720px; margin: auto; }
button, input { font: inherit; padding: .7rem; margin: .3rem 0; }
button { cursor: pointer; }
audio { width: 100%; margin-top: 1rem; }
pre { background: #222; padding: 1rem; overflow: auto; }
.error { color: #ff7b7b; }
```

**Step 3: Run frontend tests/build**

```bash
cd frontend
npm test
npm run build
```

Expected: PASS.

**Step 4: Commit**

```bash
git add frontend/src/App.jsx frontend/src/style.css
git commit -m "feat: record voice notes from browser"
```

Skipped: waveform, chat history, routing, component library. Add when the single page is annoying.

---

## Task 8: Add local mock manual test docs

**Objective:** Let us test frontend locally without renting Vast.

**Files:**

- Modify: `README.md`
- Create: `docs/streaming-frontend.md`

**Step 1: Write docs**

`docs/streaming-frontend.md`:

```markdown
# Streaming frontend

Local mock backend:

```bash
. .venv/bin/activate
MOCK_MODE=1 ARTIFACT_DIR=$PWD/artifacts uvicorn app.main:app --host 127.0.0.1 --port 7860
```

Frontend:

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open `http://127.0.0.1:5173`, record, stop, and verify:

- transcript appears
- assistant text streams token-by-token
- final WAV appears and plays

Vast backend:

Set `frontend/.env`:

```bash
VITE_BACKEND_WS=ws://<PUBLIC_HOST_OR_TUNNEL>/v1/voice-turn/ws
```

If only SSH forwarding is available:

```bash
ssh -i ~/.ssh/hermes_vast_ed25519 -p <SSH_PORT> root@<SSH_HOST> -L 7860:127.0.0.1:7860
```

Then keep frontend URL as `ws://127.0.0.1:7860/v1/voice-turn/ws`.
```

**Step 2: Link README**

Add one bullet under Docker/Vast notes:

```markdown
- Streaming token UI plan/docs: [`docs/streaming-frontend.md`](docs/streaming-frontend.md)
```

**Step 3: Commit**

```bash
git add README.md docs/streaming-frontend.md
git commit -m "docs: add streaming frontend usage"
```

---

## Task 9: Local integration verification

**Objective:** Prove the local browser path works in mock mode before GPU testing.

**Files:** none or docs updates only.

**Step 1: Start backend**

```bash
. .venv/bin/activate
MOCK_MODE=1 ARTIFACT_DIR=$PWD/artifacts uvicorn app.main:app --host 127.0.0.1 --port 7860
```

Expected:

```text
Uvicorn running on http://127.0.0.1:7860
```

**Step 2: Start frontend**

```bash
cd frontend
npm run dev
```

Expected:

```text
Local: http://127.0.0.1:5173/
```

**Step 3: Browser smoke**

Use browser automation or manual local browser:

- open `http://127.0.0.1:5173`
- click Record
- allow microphone
- say a short phrase
- click Stop + Send
- verify assistant tokens appear before final audio
- verify audio control appears and plays

**Step 4: Commit any doc corrections**

```bash
git add README.md docs/streaming-frontend.md
git commit -m "docs: clarify streaming frontend smoke test"
```

---

## Task 10: Vast integration verification

**Objective:** Prove streaming token events work against real vLLM/OmniVoice on A6000.

**Files:** none unless bugs are found.

**Step 1: Rent using existing runbook**

Use `pipecat-vast-voice-note-stack` skill. Create destroy guard.

**Step 2: Start stack**

```bash
ssh -i ~/.ssh/hermes_vast_ed25519 -p <SSH_PORT> root@<SSH_HOST> /opt/voice-stack/scripts/start_all.sh
```

**Step 3: Forward backend to local frontend**

```bash
ssh -i ~/.ssh/hermes_vast_ed25519 -p <SSH_PORT> root@<SSH_HOST> -L 7860:127.0.0.1:7860
```

**Step 4: Upload Sylens profile**

```bash
ffmpeg -y -i /Users/mali/Documents/Projects/tools/omni_voices/sylens_v2.ogg -ac 1 -ar 24000 /tmp/sylens_ref.wav
ssh -i ~/.ssh/hermes_vast_ed25519 -p <SSH_PORT> root@<SSH_HOST> 'mkdir -p /workspace/voices/profiles/sylens'
scp -i ~/.ssh/hermes_vast_ed25519 -P <SSH_PORT> /tmp/sylens_ref.wav root@<SSH_HOST>:/workspace/voices/profiles/sylens/ref_audio.wav
```

**Step 5: Browser smoke**

Run frontend locally:

```bash
cd frontend
VITE_BACKEND_WS=ws://127.0.0.1:7860/v1/voice-turn/ws npm run dev
```

Acceptance:

- frontend shows transcript from real STT
- assistant text appears incrementally via `llm_token`
- final audio is Sylens clone when `voice=clone:sylens`
- instance is destroyed after test and verified absent

**Step 6: Commit fixes only if needed**

```bash
pytest -q
cd frontend && npm test && npm run build
```

Expected: all pass before push.

---

## Delegation contract

When implementing, dispatch subagents by vertical slice, not by layer:

1. **Backend streaming client slice:** Tasks 1-2.
2. **Backend WebSocket contract slice:** Tasks 3-4.
3. **Frontend local UI slice:** Tasks 5-7.
4. **Docs + verification slice:** Tasks 8-10.

Each delegate must:

- Load `ponytail` and `software-development/tdd`.
- Write the failing test first.
- Run the exact test and include truncated output.
- Implement minimum code.
- Run all relevant tests.
- Commit only its slice.
- Avoid adding dependencies unless the plan explicitly names them.

Review gates after each delegate:

1. **Spec review:** Does the slice satisfy this plan's contract and nothing extra?
2. **Ponytail review:** What can be deleted? Did it add abstractions/config/deps we do not need?
3. **TDD review:** Was the test red before green, and is the runnable check still present?

## Non-goals for this implementation

- Real WebRTC.
- Pipecat transport graph.
- TURN/coturn.
- Audio chunk streaming from mic to STT.
- Partial STT.
- TTS audio chunk streaming.
- Barge-in/interruption.
- Auth.
- Multi-user sessions.
- Persisted chat history.

Add those after this WebSocket contract is stable and measured.
