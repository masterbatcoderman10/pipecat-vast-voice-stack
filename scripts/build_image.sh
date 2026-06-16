#!/usr/bin/env bash
set -euo pipefail
IMAGE="${IMAGE:-ghcr.io/masterbatcoderman10/pipecat-vast-voice-stack}"
TAG="${TAG:-latest}"
docker build -t "${IMAGE}:${TAG}" .
