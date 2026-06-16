#!/usr/bin/env bash
set -euo pipefail
IMAGE="${IMAGE:-ghcr.io/masterbatcoderman10/pipecat-vast-voice-stack}"
TAG="${TAG:-latest}"
USER="${GHCR_USER:-masterbatcoderman10}"
if [[ -z "${GHCR_TOKEN:-}" ]]; then
  echo "Set GHCR_TOKEN or pipe gh auth token yourself. This script will not call gh automatically." >&2
  exit 2
fi
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u "$USER" --password-stdin
docker push "${IMAGE}:${TAG}"
