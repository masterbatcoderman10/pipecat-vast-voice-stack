#!/usr/bin/env bash
set -euo pipefail
mkdir -p /workspace/artifacts /workspace/hf /var/log/voice-stack
exec supervisord -c /opt/voice-stack/docker/supervisord.conf
