#!/usr/bin/env bash
set -euo pipefail
INSTANCE_ID="${1:-${INSTANCE_ID:-}}"
[[ -n "$INSTANCE_ID" ]] || { echo "usage: $0 <instance-id>" >&2; exit 2; }
if [[ "${CONFIRM_DESTROY:-}" != "YES" ]]; then
  echo "Refusing to destroy without CONFIRM_DESTROY=YES" >&2
  exit 2
fi
command -v vastai >/dev/null || { echo "vastai CLI not found" >&2; exit 127; }
vastai destroy instance "$INSTANCE_ID"
for _ in $(seq 1 20); do
  if ! vastai show instance "$INSTANCE_ID" >/tmp/vast-destroy-check 2>&1; then
    echo "Instance $INSTANCE_ID no longer shown."
    exit 0
  fi
  if ! grep -Eiq 'running|rented|active' /tmp/vast-destroy-check; then
    cat /tmp/vast-destroy-check
    echo "Instance $INSTANCE_ID appears destroyed/inactive."
    exit 0
  fi
  sleep 10
done
echo "Could not verify destruction for $INSTANCE_ID" >&2
exit 1
