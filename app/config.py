from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    mock_mode: bool = False
    port: int = 7860
    stt_port: int = 9001
    brain_port: int = 9002
    tts_port: int = 9003
    stt_model: str = "nvidia/nemotron-speech-streaming-en-0.6b"
    brain_model: str = "LiquidAI/LFM2.5-8B-A1B"
    brain_served_model: str = "lfm2.5-8b-a1b"
    tts_model: str = "k2-fsa/OmniVoice"
    voice_profile: str = "sylens"
    hf_home: str = "/workspace/hf"
    model_cache_dir: str = "/workspace/hf"
    artifact_dir: Path = Path("/workspace/artifacts")
    max_model_len: int = 8192
    gpu_memory_utilization: float = 0.82
    request_timeout_s: float = 120.0

    @property
    def stt_url(self) -> str:
        return f"http://127.0.0.1:{self.stt_port}"

    @property
    def brain_url(self) -> str:
        return f"http://127.0.0.1:{self.brain_port}"

    @property
    def tts_url(self) -> str:
        return f"http://127.0.0.1:{self.tts_port}"


def get_settings() -> Settings:
    return Settings(
        mock_mode=_bool_env("MOCK_MODE", False),
        port=int(os.getenv("PORT", "7860")),
        stt_port=int(os.getenv("STT_PORT", "9001")),
        brain_port=int(os.getenv("BRAIN_PORT", "9002")),
        tts_port=int(os.getenv("TTS_PORT", "9003")),
        stt_model=os.getenv("STT_MODEL", "nvidia/nemotron-speech-streaming-en-0.6b"),
        brain_model=os.getenv("BRAIN_MODEL", "LiquidAI/LFM2.5-8B-A1B"),
        brain_served_model=os.getenv("BRAIN_SERVED_MODEL", "lfm2.5-8b-a1b"),
        tts_model=os.getenv("TTS_MODEL", "k2-fsa/OmniVoice"),
        voice_profile=os.getenv("VOICE_PROFILE", "sylens"),
        hf_home=os.getenv("HF_HOME", "/workspace/hf"),
        model_cache_dir=os.getenv("MODEL_CACHE_DIR", os.getenv("HF_HOME", "/workspace/hf")),
        artifact_dir=Path(os.getenv("ARTIFACT_DIR", "/workspace/artifacts")),
        max_model_len=int(os.getenv("MAX_MODEL_LEN", "8192")),
        gpu_memory_utilization=float(os.getenv("GPU_MEMORY_UTILIZATION", "0.82")),
        request_timeout_s=float(os.getenv("REQUEST_TIMEOUT_S", "120")),
    )
