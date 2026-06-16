#!/usr/bin/env bash
set -euo pipefail
IMAGE="${IMAGE:-ghcr.io/masterbatcoderman10/pipecat-vast-voice-stack}"
TAG="${TAG:-latest}"
NAME="${TEMPLATE_NAME:-Pipecat Voice Stack A6000 - Nemotron LFM OmniVoice}"
: "${HF_TOKEN:?Set HF_TOKEN before creating a Vast template}"
command -v vastai >/dev/null || { echo "vastai CLI not found" >&2; exit 127; }
vastai create template \
  --name "$NAME" \
  --image "$IMAGE" \
  --image_tag "$TAG" \
  --env "-e HF_TOKEN=${HF_TOKEN} -e HF_HOME=/workspace/hf -e MODEL_CACHE_DIR=/workspace/hf -e MAX_MODEL_LEN=${MAX_MODEL_LEN:-8192} -p 7860:7860 -p 9001:9001 -p 9002:9002 -p 9003:9003" \
  --onstart-cmd "/opt/voice-stack/scripts/start_all.sh" \
  --disk_space "${DISK_SPACE:-150}" \
  --ssh \
  --direct \
  --search_params "gpu_name=RTX_A6000 gpu_ram>=48 disk_space>=150 inet_down>200 inet_up>50 direct_port_count>=5 rented=False"
