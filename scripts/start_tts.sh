#!/usr/bin/env bash
set -euo pipefail
if [[ "${MOCK_MODE:-0}" =~ ^(1|true|TRUE|yes|on)$ ]]; then
  exec python3 -m uvicorn services.tts_adapter_server:app --host 0.0.0.0 --port "${TTS_PORT:-9003}"
fi
exec omnivoice-server \
  --host 0.0.0.0 \
  --port "${TTS_PORT:-9003}" \
  --device cuda \
  --model "${TTS_MODEL:-k2-fsa/OmniVoice}" \
  --profile-dir "${PROFILE_DIR:-/workspace/voices/profiles}" \
  --log-level info \
  --timeout 600
