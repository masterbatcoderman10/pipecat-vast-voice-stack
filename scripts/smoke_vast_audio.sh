#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${BASE_URL:-http://127.0.0.1:7860}"
AUDIO="${1:-tests/fixtures/sample.wav}"
OUT_DIR="${OUT_DIR:-runs/smoke-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$OUT_DIR"
curl -fsS "$BASE_URL/health" | tee "$OUT_DIR/health.json"
curl -fsS "$BASE_URL/v1/models" | tee "$OUT_DIR/models.json"
curl -fsS -X POST "$BASE_URL/v1/voice-turn" \
  -F "file=@${AUDIO};type=audio/wav" \
  -F "prompt_preamble=Answer briefly for a smoke test." \
  -F "voice=${VOICE:-default}" \
  -F "stream=false" | tee "$OUT_DIR/result.json"
python3 - <<'PY' "$OUT_DIR/result.json" > "$OUT_DIR/audio_url.txt"
import json, sys
print(json.load(open(sys.argv[1]))['audio_url'])
PY
curl -fsS "$BASE_URL$(cat "$OUT_DIR/audio_url.txt")" -o "$OUT_DIR/output.wav"
echo "Saved smoke outputs in $OUT_DIR"
