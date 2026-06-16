#!/usr/bin/env bash
set -euo pipefail
INSTANCE_ID="${1:-${INSTANCE_ID:-}}"
MINUTES="${GUARD_MINUTES:-55}"
[[ -n "$INSTANCE_ID" ]] || { echo "usage: $0 <instance-id>" >&2; exit 2; }
echo "Guard started for $INSTANCE_ID; will destroy in $MINUTES minutes unless killed."
sleep "$((MINUTES * 60))"
CONFIRM_DESTROY=YES "$(dirname "$0")/destroy_vast_instance.sh" "$INSTANCE_ID"
