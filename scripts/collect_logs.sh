#!/usr/bin/env bash
set -euo pipefail
INSTANCE_ID="${1:-${INSTANCE_ID:-}}"
OUT_DIR="${OUT_DIR:-runs/logs-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$OUT_DIR"
if [[ -n "$INSTANCE_ID" ]] && command -v vastai >/dev/null; then
  vastai logs "$INSTANCE_ID" > "$OUT_DIR/vast.log" 2>&1 || true
  vastai show instance "$INSTANCE_ID" --raw > "$OUT_DIR/instance.json" 2>&1 || true
fi
if [[ -d /var/log/voice-stack ]]; then
  cp -R /var/log/voice-stack "$OUT_DIR/service-logs" || true
fi
echo "Collected logs in $OUT_DIR"
