#!/usr/bin/env bash
set -euo pipefail
INSTANCE_ID="${1:-${INSTANCE_ID:-}}"
[[ -n "$INSTANCE_ID" ]] || { echo "usage: $0 <instance-id>" >&2; exit 2; }
command -v vastai >/dev/null || { echo "vastai CLI not found" >&2; exit 127; }
DEADLINE=$((SECONDS + ${WAIT_TIMEOUT_S:-900}))
while (( SECONDS < DEADLINE )); do
  vastai show instance "$INSTANCE_ID" --raw | tee "${STATUS_FILE:-/tmp/vast-${INSTANCE_ID}.json}" || true
  if vastai ssh-url "$INSTANCE_ID" >/tmp/vast-ssh-url 2>/dev/null; then
    echo "SSH URL: $(cat /tmp/vast-ssh-url)"
  fi
  if curl -fsS "${BASE_URL:-http://127.0.0.1:7860}/health" >/dev/null 2>&1; then
    echo "HTTP health ready"
    exit 0
  fi
  sleep 15
done
echo "Timed out waiting for Vast readiness" >&2
exit 1
