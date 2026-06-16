# Streaming frontend

The local React UI records one browser `MediaRecorder` blob, sends it to `/v1/voice-turn/ws`, displays transcript and streaming `llm_token` events, then plays the returned WAV. The default backend URL is `ws://127.0.0.1:7860/v1/voice-turn/ws`; the default voice is `clone:sylens`.

## Local mock backend

```bash
. .venv/bin/activate
MOCK_MODE=1 ARTIFACT_DIR=$PWD/artifacts uvicorn app.main:app --host 127.0.0.1 --port 7860
```

## Frontend

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

## Vast backend

Set `frontend/.env`:

```bash
VITE_BACKEND_WS=ws://<PUBLIC_HOST_OR_TUNNEL>/v1/voice-turn/ws
```

If only SSH forwarding is available:

```bash
ssh -i ~/.ssh/hermes_vast_ed25519 -p <SSH_PORT> root@<SSH_HOST> -L 7860:127.0.0.1:7860
```

Then keep frontend URL as `ws://127.0.0.1:7860/v1/voice-turn/ws`.
