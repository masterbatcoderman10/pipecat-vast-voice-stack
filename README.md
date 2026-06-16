# Pipecat Vast Voice Stack

Backend-only scaffold for a Pipecat-style voice stack intended for a Vast.ai RTX A6000 Docker image.

## What is included

- FastAPI service with:
  - `GET /health`
  - `GET /v1/models`
  - `POST /v1/audio/transcriptions`
  - `POST /v1/chat/completions`
  - `POST /v1/audio/speech`
  - `POST /v1/voice-turn`
  - `GET /artifacts/{name}`
- Mock mode (`MOCK_MODE=1`) for local CPU/GPU-free tests.
- Lazy Nemotron STT adapter stub that imports NeMo only outside mock mode.
- Dockerfile, supervisor config, model-server startup scripts, and Vast helper scripts.

## Local development

```bash
cd /Users/mali/Documents/Projects/r_and_d/pipecat-vast-voice-stack
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
MOCK_MODE=1 ARTIFACT_DIR=$PWD/artifacts pytest -q
MOCK_MODE=1 ARTIFACT_DIR=$PWD/artifacts uvicorn app.main:app --host 127.0.0.1 --port 7860
```

Smoke request:

```bash
MOCK_MODE=1 BASE_URL=http://127.0.0.1:7860 scripts/smoke_vast_audio.sh tests/fixtures/sample.wav
```

## Docker/Vast notes

Do not rent Vast until the image is built and published. Helper scripts are present but guarded where they would create/destroy paid resources.

- Build only: `scripts/build_image.sh`
- Push after setting `GHCR_TOKEN`: `scripts/push_image.sh`
- Create template after verifying Vast CLI syntax: `scripts/create_vast_template.sh`
- Rent requires explicit `CONFIRM_RENT=YES`.
- Destroy requires explicit `CONFIRM_DESTROY=YES`.

Heavy GPU package pins (NeMo, vLLM/SGLang, OmniVoice, Pipecat) are intentionally left for CUDA image validation because this task only implements the local backend contracts and mock tests.
