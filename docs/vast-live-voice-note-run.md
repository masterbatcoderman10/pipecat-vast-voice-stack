# Vast Live Voice-Note Runbook

This repo/image has been validated on a Vast.ai RTX A6000 as a voice-note exchange backend: user sends a complete audio clip, the backend returns a complete WAV response. It is not realtime WebRTC/WebSocket streaming yet.

## Image

```text
ghcr.io/masterbatcoderman10/pipecat-vast-voice-stack:latest
```

Validated commit lineage:

- `60b4216` — initial stack scaffold
- `d659643` — supervisor working-directory fix
- `dea0ed6` — Vast runtime smoke fixes, including OmniVoice voice fallback handling and pytest pythonpath config

## Vast offer/rental shape

Use an RTX A6000 48GB or better, 150GB disk, SSH direct.

Example search:

```bash
vastai search offers 'gpu_name=RTX_A6000 num_gpus=1 rentable=true verified=true rented=false dph<=0.70 disk_space>=150 inet_down>100 direct_port_count>=4 reliability>0.95' --storage 150 --raw -o 'dph' --limit 5
```

Example create:

```bash
vastai create instance <OFFER_ID> \
  --image ghcr.io/masterbatcoderman10/pipecat-vast-voice-stack:latest \
  --disk 150 \
  --ssh --direct \
  --env '-p 7860:7860 -p 9001:9001 -p 9002:9002 -p 9003:9003' \
  --label pipecat-live-voice-note \
  --cancel-unavail
```

Attach SSH key if needed:

```bash
vastai attach ssh <INSTANCE_ID> ~/.ssh/hermes_vast_ed25519.pub
```

Important: run `vastai` from a clean shell if a project venv is active. The CLI uses `#!/usr/bin/env python3`, so a venv can break it with missing `requests`.

```bash
unset VIRTUAL_ENV VIRTUAL_ENV_PROMPT PYTHONPATH
```

## Startup gotcha

With `--image ... --ssh --direct`, Vast's SSH bootstrap may not leave the image `CMD` running as the app process. After SSH succeeds, manually start the stack for smoke tests:

```bash
ssh -i ~/.ssh/hermes_vast_ed25519 -p <SSH_PORT> root@<SSH_HOST> /opt/voice-stack/scripts/start_all.sh
```

For an interactive/agent-run smoke test, keep this command as a tracked background process, then run checks in separate SSH calls.

## Readiness checks

```bash
curl -sS http://127.0.0.1:7860/health
curl -sS http://127.0.0.1:7860/v1/models
curl -sS http://127.0.0.1:9003/health
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader
```

Expected health:

```json
{"status":"ok","mock_mode":false,"artifact_dir":"/workspace/artifacts"}
```

## Voice-note flow

Current supported mode is full-turn audio, not live streaming:

```text
full user audio clip -> STT -> LLM -> TTS -> full WAV reply
```

Endpoints:

- `POST /v1/voice-turn` with multipart file: returns JSON containing transcript, assistant text, timings, and `audio_url`.
- `POST /v1/voice-turn` with `stream=true`: returns the final WAV directly after the whole pipeline completes.
- `POST /v1/audio/speech`: returns WAV for input text.
- `POST /v1/chat/completions`: OpenAI-ish chat passthrough.

## Sylens clone setup

The image does not contain the `sylens` clone profile. Upload a local reference audio to this exact path on the Vast box:

```text
/workspace/voices/profiles/sylens/ref_audio.wav
```

Working local reference used in the live test:

```text
/Users/mali/Documents/Projects/tools/omni_voices/sylens_v2.ogg
```

Convert/upload:

```bash
ffmpeg -y -i /Users/mali/Documents/Projects/tools/omni_voices/sylens_v2.ogg -ac 1 -ar 24000 /tmp/sylens_ref.wav
ssh -i ~/.ssh/hermes_vast_ed25519 -p <SSH_PORT> root@<SSH_HOST> 'mkdir -p /workspace/voices/profiles/sylens'
scp -i ~/.ssh/hermes_vast_ed25519 -P <SSH_PORT> /tmp/sylens_ref.wav root@<SSH_HOST>:/workspace/voices/profiles/sylens/ref_audio.wav
```

Then request TTS with:

```json
{"input":"I'm doing great, thanks for sending the audio sample!","voice":"clone:sylens"}
```

Note: `voice=sylens` is invalid for OmniVoice. Use `clone:sylens`. If no profile exists, omit `voice` or the service returns `422 Unsupported voice value`.

## Example: generate a Sylens reply from text

```bash
curl -sS --max-time 180 http://127.0.0.1:7860/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"I am doing great, thanks for sending the audio sample!","voice":"clone:sylens"}' \
  -o /tmp/reply_sylens.wav
```

## Live validation results

Two paid Vast runs were performed and destroyed.

First validation run:

- Instance: `41164144`
- GPU: RTX A6000 48GB
- Health: OK
- Full `/v1/voice-turn`: OK
- Approx timings on sample generated audio:
  - STT: 62.4s
  - LLM: 4.9s
  - TTS: 7.5s
  - Total: 74.9s
- Destroy verification: `FOUND_41164144=False`

Second live voice-note demo:

- Instance: `41167205`
- User audio transcript provided by Telegram: `Hi, this is an audio sample. How are you doing?`
- Generated default reply WAV successfully.
- Uploaded Sylens reference profile and regenerated reply with `voice=clone:sylens` successfully.
- Destroy verification: `FOUND_41167205=False`

Local artifacts from the second run:

```text
/Users/mali/Documents/Projects/r_and_d/pipecat-vast-voice-stack/live-voice-replies/41167205/reply.wav
/Users/mali/Documents/Projects/r_and_d/pipecat-vast-voice-stack/live-voice-replies/41167205/reply_sylens.wav
```

## Cleanup

Destroy, do not stop, paid test instances:

```bash
vastai destroy instance <INSTANCE_ID>
sleep 8
vastai show instances --raw
```

Verify the ID is absent from active instances.

## Known limitations

- Not live streaming conversation yet; it returns full response audio after the whole turn completes.
- No barge-in/interruption handling.
- No WebSocket/WebRTC endpoint yet.
- Nemotron STT was slow in cold/live tests; consider replacing or optimizing before realtime use.
- Vast normal containers are not full VMs; Docker-in-Docker should not be assumed.
