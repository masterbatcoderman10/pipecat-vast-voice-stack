# Realtime Pipecat VAD Streaming Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Replace the current full-clip voice-turn demo with a true realtime voice conversation pipeline: browser mic frames stream in continuously, Pipecat/VAD detects turns, STT emits interim/final transcripts, LLM tokens stream as soon as the turn is ready, and TTS audio chunks stream back while synthesis is still in progress.

**Architecture:** Move from a request/response WebSocket (`start -> one audio blob -> end -> full WAV`) to a bidirectional realtime session (`session.start -> audio.input chunks -> VAD events -> STT partial/final -> LLM tokens -> TTS audio chunks`). Implement a deterministic local mock first, then swap in Pipecat processors and OmniVoice streaming if the server exposes a usable streaming/chunk API. If OmniVoice's installed server only exposes full-response `/v1/audio/speech`, add a streaming adapter that chunks sentence-level or PCM-level output and mark it as pseudo-streaming until real server chunking is verified.

**Tech Stack:** FastAPI WebSocket, Pipecat `pipecat-ai`, VAD analyzer/processor, browser Web Audio API + AudioWorklet, React/Vite, vLLM/OpenAI-compatible streaming, OmniVoice/omnivoice-server, pytest + node:test.

---

## Reality Check

The current implementation is **not** true end-to-end token-to-audio streaming.

Current path:

```text
browser records complete MediaRecorder blob
-> backend receives full WebM/WAV after Stop
-> ffmpeg transcodes to WAV
-> STT runs on whole clip
-> vLLM streams text tokens
-> backend accumulates full assistant text
-> OmniVoice synthesizes one complete WAV
-> browser receives one final audio blob
```

What is genuinely streaming today:

```text
LLM text tokens only
```

What is not streaming today:

```text
mic frames, VAD turn detection, partial STT, incremental TTS audio, barge-in
```

Target path:

```text
browser AudioWorklet PCM frames
-> WS binary chunks every 20ms
-> Pipecat/VAD detects speech start/stop
-> STT emits interim/final transcript events
-> LLM emits visible tokens
-> text segmenter emits speakable clauses/sentences
-> TTS emits audio chunks as early as possible
-> browser jitter buffer plays chunks immediately
```

## Key Unknown: OmniVoice Streaming Contract

Before promising token-to-audio, verify the exact `omnivoice-server` contract installed in the image.

Acceptance paths:

1. **Best:** OmniVoice exposes a streaming HTTP/SSE/WebSocket endpoint that yields audio chunks before full synthesis completion.
2. **Acceptable v1:** OmniVoice only exposes full WAV, so backend starts synthesis per sentence/clause and streams each resulting WAV/PCM segment as soon as that segment finishes. This is sentence-level streaming, not token-level audio.
3. **Fallback:** Replace/augment OmniVoice with a TTS engine that provides native streaming audio frames if true first-audio-token latency is the priority.

The implementation must label which path is active in `/health/realtime` and in frontend debug UI.

## Protocol v2

Endpoint:

```text
WS /v2/realtime/ws
```

Client -> server text events:

```json
{"type":"session.start","session_id":"uuid","sample_rate":16000,"channels":1,"encoding":"pcm_s16le","voice":"clone:sylens","vad":{"enabled":true,"threshold":0.5}}
{"type":"audio.input.commit"}
{"type":"session.stop"}
{"type":"response.cancel"}
```

Client -> server binary frames:

```text
raw PCM s16le mono 16k frames, ideally 20ms = 640 bytes
```

Server -> client text events:

```json
{"type":"session.ready","session_id":"uuid","mode":"mock|live","tts_streaming":"native|sentence|none"}
{"type":"vad.speech_start","ts_ms":123}
{"type":"vad.speech_stop","ts_ms":812}
{"type":"stt.partial","text":"hey can you"}
{"type":"stt.final","text":"hey can you hear me"}
{"type":"llm.start"}
{"type":"llm.token","text":"Yes"}
{"type":"llm.segment","text":"Yes, I can hear you."}
{"type":"tts.start","format":"pcm_s16le","sample_rate":24000}
{"type":"tts.audio_start","segment_id":1}
{"type":"tts.audio_done","segment_id":1,"bytes":9600}
{"type":"response.done","turn_id":"uuid","timings":{"vad_ms":120,"stt_final_ms":480,"first_token_ms":230,"first_audio_ms":900}}
{"type":"error","message":"...","recoverable":true}
```

Server -> client binary frames:

```text
PCM audio chunks for playback, preceded by `tts.audio_start` metadata. For browser simplicity v1 can use WAV segment chunks, but true low-latency playback should use PCM with AudioWorklet.
```

## Acceptance Criteria

- Browser captures mic continuously, not with full-clip MediaRecorder stop/send.
- Backend receives audio chunks before user stops speaking.
- VAD emits `vad.speech_start` and `vad.speech_stop` events.
- STT can emit at least final transcript per VAD turn; partial transcript if the backend model/API supports it.
- LLM emits visible `llm.token` events without `<think>` leakage.
- TTS emits at least one playable audio chunk before the full assistant response is finished.
- Frontend begins playback before `response.done`.
- Sylens remains the default voice: `clone:sylens`.
- Barge-in v1: user speech while assistant audio is playing sends `response.cancel`, stops local playback, and cancels queued TTS segments.
- Tests prove protocol ordering and audio chunk behavior in mock mode.

## Implementation Tasks

### Task 1: Add realtime protocol reducer tests

**Objective:** Lock the frontend/backend event contract before implementation.

**Files:**
- Modify: `frontend/src/protocol.js`
- Modify: `frontend/src/protocol.test.js`

**Step 1: Write failing tests**

Add tests for:

```js
// session.ready -> listening
// vad.speech_start -> user_speaking
// vad.speech_stop -> transcribing
// stt.partial accumulates interim transcript
// stt.final freezes final transcript and status=thinking
// llm.token appends assistant text
// tts.audio_start -> speaking
// response.done -> idle with timings
// error -> error
```

**Step 2: Run test**

```bash
cd frontend && npm test
```

Expected: FAIL because v2 events are not handled.

**Step 3: Implement reducer support**

Update `reduceEvent` to support the v2 event types while preserving current `/v1/voice-turn/ws` behavior.

**Step 4: Verify**

```bash
cd frontend && npm test && npm run build
```

Expected: PASS.

**Step 5: Commit**

```bash
git add frontend/src/protocol.js frontend/src/protocol.test.js
git commit -m "feat: add realtime protocol reducer"
```

### Task 2: Create backend realtime session state machine in mock mode

**Objective:** Add `/v2/realtime/ws` with deterministic mock VAD/STT/LLM/TTS events, no GPU required.

**Files:**
- Create: `app/realtime/protocol.py`
- Create: `app/realtime/session.py`
- Modify: `app/main.py`
- Test: `tests/test_realtime_ws.py`

**Step 1: Write failing backend test**

Test should:

1. Connect to `/v2/realtime/ws` with `MOCK_MODE=1`.
2. Send `session.start`.
3. Send a few binary PCM chunks.
4. Send `audio.input.commit`.
5. Assert ordered events:

```text
session.ready
vad.speech_start
vad.speech_stop
stt.final
llm.start
llm.token
llm.segment
tts.start
tts.audio_start
(binary audio chunk)
tts.audio_done
response.done
```

6. Assert at least one binary audio frame arrives before `response.done`.

**Step 2: Run failing test**

```bash
MOCK_MODE=1 pytest tests/test_realtime_ws.py -q
```

Expected: FAIL because endpoint does not exist.

**Step 3: Implement mock session**

Implement a minimal `RealtimeSession`:

- Accepts `session.start`.
- Buffers binary audio chunks.
- Emits synthetic VAD once the first non-empty chunk arrives.
- On `audio.input.commit`, emits fixed transcript: `Mock realtime transcript`.
- Streams mock LLM tokens: `Mock`, ` realtime`, ` reply.`.
- Emits one small tone WAV/PCM binary chunk immediately after `tts.audio_start`.
- Emits `response.done` last.

**Step 4: Verify**

```bash
MOCK_MODE=1 pytest tests/test_realtime_ws.py -q
MOCK_MODE=1 pytest tests/ -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/realtime app/main.py tests/test_realtime_ws.py
git commit -m "feat: add mock realtime websocket"
```

### Task 3: Replace frontend MediaRecorder with AudioWorklet PCM streaming mode

**Objective:** Browser sends live PCM chunks instead of a complete WebM blob.

**Files:**
- Create: `frontend/public/pcm-worklet.js`
- Create: `frontend/src/realtimeClient.js`
- Modify: `frontend/src/App.jsx`
- Test: `frontend/src/realtimeClient.test.js`

**Step 1: Write failing tests**

Add pure JS tests for:

- `float32ToPcm16()` clamps and converts samples.
- `buildSessionStart()` defaults `voice` to `clone:sylens`.
- client maps binary audio chunks into a playback queue callback.

**Step 2: Run failing tests**

```bash
cd frontend && npm test
```

Expected: FAIL.

**Step 3: Implement realtime client**

- `RealtimeVoiceClient` opens `/v2/realtime/ws`.
- Sends `session.start` on open.
- Registers AudioWorklet processor.
- Streams 20ms PCM chunks as WebSocket binary frames.
- Sends `audio.input.commit` when user taps stop or VAD client-side stop is later detected.
- Plays incoming audio chunks through an `AudioContext` queue.

Keep the old full-clip UI under a `Legacy mode` toggle for fallback.

**Step 4: Verify**

```bash
cd frontend && npm test && npm run build
```

Expected: PASS.

**Step 5: Commit**

```bash
git add frontend/public frontend/src frontend/package.json
git commit -m "feat: stream browser pcm over realtime websocket"
```

### Task 4: Add Pipecat VAD adapter behind `/v2/realtime/ws`

**Objective:** Use Pipecat's natural VAD pipeline for turn detection in live mode.

**Files:**
- Create: `app/realtime/vad.py`
- Modify: `app/realtime/session.py`
- Modify: `requirements.txt` / `Dockerfile` only if additional Pipecat extras are needed
- Test: `tests/test_realtime_vad.py`

**Step 1: Research exact Pipecat VAD APIs inside the current environment**

Run locally if package is available, otherwise inside a Vast validation instance later:

```bash
python - <<'PY'
import pipecat
import pkgutil
mods=[m.name for m in pkgutil.walk_packages(pipecat.__path__, pipecat.__name__+'.') if 'vad' in m.name.lower()]
print('\n'.join(mods))
PY
```

Look for Silero/WebRTC VAD analyzer classes and required sample format.

**Step 2: Write failing tests**

Use generated silence/tone PCM frames to assert:

- silence does not emit speech start.
- tone/speech-like frame can trigger a `speech_start` in mock/fake analyzer.
- adapter emits `speech_stop` after configured silence duration.

**Step 3: Implement adapter**

Implement a small interface first:

```python
class VadAdapter:
    async def feed_pcm(self, pcm: bytes) -> list[VadEvent]: ...
```

Then wire Pipecat analyzer behind it when `MOCK_MODE=0`.

**Step 4: Verify**

```bash
MOCK_MODE=1 pytest tests/test_realtime_vad.py tests/test_realtime_ws.py -q
```

**Step 5: Commit**

```bash
git add app/realtime tests/test_realtime_vad.py requirements.txt Dockerfile
git commit -m "feat: add pipecat vad adapter"
```

### Task 5: Add incremental STT boundary

**Objective:** Feed VAD turns to STT with a streaming-ready interface.

**Files:**
- Create: `app/realtime/stt_stream.py`
- Modify: `app/realtime/session.py`
- Test: `tests/test_realtime_stt.py`

**Implementation strategy:**

Start with turn-final STT because current Nemotron adapter is file/batch oriented. Keep the interface streaming-shaped so we can replace internals when a true partial STT API is verified.

```python
class StreamingSttAdapter:
    async def feed_audio(self, pcm: bytes) -> list[SttEvent]: ...
    async def finalize_turn(self) -> SttEvent: ...
```

Mock mode should emit `stt.partial` while chunks arrive and `stt.final` on VAD stop/commit.

Live mode v1 can buffer one VAD segment and call existing STT, then emit `stt.final`.

**Acceptance:** No full browser-recording blob; STT receives frames incrementally even if final transcript is produced at turn boundary.

### Task 6: Add text segmentation for speakable units

**Objective:** Convert LLM token stream into chunks suitable for early TTS.

**Files:**
- Create: `app/realtime/text_segmenter.py`
- Test: `tests/test_text_segmenter.py`

**Behavior:**

- Accumulate LLM tokens.
- Hide `<think>...</think>` using existing `ThinkFilter` semantics.
- Emit a segment when encountering sentence-ending punctuation, newline, or a max character threshold.
- Never emit empty/internal-only segments.

**Acceptance:** First `llm.segment` event happens before `llm_done` when enough text arrives.

### Task 7: Add TTS streaming adapter

**Objective:** Stream audio chunks back before the full response is done.

**Files:**
- Create: `app/realtime/tts_stream.py`
- Modify: `app/realtime/session.py`
- Test: `tests/test_realtime_tts.py`

**Research gate:** Inspect `omnivoice-server` for real streaming support.

Commands for a validation instance:

```bash
python3 - <<'PY'
import inspect, omnivoice_server
print(omnivoice_server)
PY
python3 - <<'PY'
import pkgutil, omnivoice_server
for m in pkgutil.walk_packages(omnivoice_server.__path__, omnivoice_server.__name__+'.'):
    if 'stream' in m.name.lower() or 'audio' in m.name.lower():
        print(m.name)
PY
curl -sS http://127.0.0.1:9003/openapi.json | python3 -m json.tool | grep -i -C 3 stream
```

**Implementation paths:**

- If native streaming exists: consume streaming endpoint and forward each PCM/WAV chunk as binary immediately.
- If not: sentence-streaming fallback:
  - consume `llm.segment` events,
  - call OmniVoice per segment,
  - convert each WAV segment to raw PCM or send WAV segment metadata,
  - stream segment audio as soon as that segment completes,
  - overlap LLM generation and segment TTS with an async queue.

**Acceptance:** Test proves binary audio arrives before `response.done`; live smoke should report `tts_streaming=native` or `sentence`.

### Task 8: Implement barge-in and cancellation

**Objective:** If user starts speaking while assistant audio is queued/playing, cancel response generation and stop playback.

**Files:**
- Modify: `app/realtime/session.py`
- Modify: `frontend/src/realtimeClient.js`
- Test: `tests/test_realtime_barge_in.py`, `frontend/src/realtimeClient.test.js`

**Behavior:**

- Client sends `response.cancel` when local mic energy/VAD fires during assistant playback.
- Server cancels active LLM/TTS tasks and drains queued segments.
- Server emits `response.cancelled`.
- Frontend clears playback buffer immediately.

### Task 9: Add realtime health/debug endpoints

**Objective:** Make it obvious what mode is actually running.

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_realtime_health.py`

Endpoint:

```text
GET /health/realtime
```

Response:

```json
{
  "status":"ok",
  "vad":"pipecat|mock",
  "stt_streaming":"partial|turn-final|mock",
  "llm_streaming":true,
  "tts_streaming":"native|sentence|none|mock",
  "audio_input":"pcm_s16le_16k",
  "audio_output":"pcm_s16le_24k|wav_segments"
}
```

### Task 10: Vast validation and demo handoff

**Objective:** Validate on a fresh short-lived Vast A6000 after local mock tests pass.

**Steps:**

1. Build and push GHCR image.
2. Rent A6000 with destroy guard first.
3. Start backend and verify:

```bash
curl http://127.0.0.1:7860/health
curl http://127.0.0.1:7860/health/realtime
curl http://127.0.0.1:9003/health
```

4. Upload Sylens to:

```text
/workspace/voices/profiles/sylens/ref_audio.wav
```

5. Run CLI WSS smoke using generated PCM chunks:

```text
session.ready -> vad.speech_start -> vad.speech_stop -> stt.final -> llm.token -> tts.audio_start -> binary before response.done
```

6. Start local frontend production preview bound to `0.0.0.0:5173`.
7. Expose backend and frontend through fresh Cloudflare quick tunnels.
8. Verify served frontend bundle includes the current backend WSS and `clone:sylens`.
9. Send only the verified frontend URL.
10. Destroy instance when user is done and verify active instances are empty.

## Explicit Non-Goals for First Realtime Upgrade

- No WebRTC/TURN until WS PCM path proves the pipeline.
- No multi-user sessions.
- No persistence of audio recordings.
- No promise of native OmniVoice streaming until the installed server contract is verified.
- No Docker-in-Docker validation on normal Vast containers.

## Definition of Done

- `MOCK_MODE=1 pytest tests/ -q` passes.
- `cd frontend && npm test && npm run build` passes.
- `/v2/realtime/ws` mock smoke proves binary audio arrives before `response.done`.
- Live Vast smoke proves the same ordering with `clone:sylens`.
- `/health/realtime` accurately labels whether TTS is native-streaming or sentence-streaming.
- README documents the difference between v1 full-turn relay and v2 realtime pipeline.
