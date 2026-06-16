#!/usr/bin/env bash
set -euo pipefail
if [[ "${MOCK_MODE:-0}" =~ ^(1|true|TRUE|yes|on)$ ]]; then
  exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${BRAIN_PORT:-9002}"
fi
exec python3 -m vllm.entrypoints.openai.api_server \
  --host 0.0.0.0 \
  --port "${BRAIN_PORT:-9002}" \
  --model "${BRAIN_MODEL:-LiquidAI/LFM2.5-8B-A1B}" \
  --served-model-name "${BRAIN_SERVED_MODEL:-lfm2.5-8b-a1b}" \
  --max-model-len "${MAX_MODEL_LEN:-8192}" \
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION:-0.82}" \
  --trust-remote-code
