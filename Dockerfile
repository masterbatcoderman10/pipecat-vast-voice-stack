FROM vllm/vllm-openai:latest

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860 \
    STT_PORT=9001 \
    BRAIN_PORT=9002 \
    TTS_PORT=9003 \
    HF_HOME=/workspace/hf \
    MODEL_CACHE_DIR=/workspace/hf \
    ARTIFACT_DIR=/workspace/artifacts

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg git curl ca-certificates supervisor libsndfile1 build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/voice-stack
COPY requirements.txt ./
RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install -r requirements.txt \
    && python3 -m pip install "nemo_toolkit[asr]" omnivoice-server soundfile
COPY app ./app
COPY services ./services
COPY scripts ./scripts
COPY docker ./docker
RUN chmod +x scripts/*.sh && mkdir -p /workspace/hf /workspace/artifacts /var/log/voice-stack

EXPOSE 7860 9001 9002 9003
CMD ["/opt/voice-stack/scripts/start_all.sh"]
