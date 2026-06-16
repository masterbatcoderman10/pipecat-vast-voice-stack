#!/usr/bin/env bash
set -euo pipefail
command -v vastai >/dev/null || { echo "vastai CLI not found" >&2; exit 127; }
if [[ "${CONFIRM_RENT:-}" != "YES" ]]; then
  echo "Refusing to rent without CONFIRM_RENT=YES" >&2
  exit 2
fi
RUN_DIR="runs/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$RUN_DIR"
SEARCH='gpu_name=RTX_A6000 gpu_ram>=48 dph_total<=0.70 disk_space>=150 direct_port_count>=5 rented=False'
vastai search offers "$SEARCH" --raw > "$RUN_DIR/offers.json"
python3 - <<'PY' "$RUN_DIR/offers.json" > "$RUN_DIR/offer_id.txt"
import json, sys
rows=json.load(open(sys.argv[1]))
if not rows:
    raise SystemExit('no matching A6000 offers')
rows=sorted(rows, key=lambda r: float(r.get('dph_total', 999)))
print(rows[0].get('id') or rows[0].get('ask_contract_id'))
PY
OFFER_ID=$(cat "$RUN_DIR/offer_id.txt")
echo "Selected offer: $OFFER_ID"
if [[ -n "${TEMPLATE_ID:-}" ]]; then
  vastai create instance "$OFFER_ID" --template_hash "$TEMPLATE_ID" --raw | tee "$RUN_DIR/instance.json"
else
  IMAGE="${IMAGE:-ghcr.io/masterbatcoderman10/pipecat-vast-voice-stack:latest}"
  vastai create instance "$OFFER_ID" --image "$IMAGE" --disk "${DISK_SPACE:-150}" --env "-e HF_TOKEN=${HF_TOKEN:-} -p 7860:7860 -p 9001:9001 -p 9002:9002 -p 9003:9003" --raw | tee "$RUN_DIR/instance.json"
fi
echo "$RUN_DIR"
