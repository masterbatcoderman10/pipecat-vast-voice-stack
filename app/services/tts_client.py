from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import Settings
from app.utils.audio import generate_tone_wav


@dataclass
class TtsResult:
    audio: bytes
    first_audio_ms: int
    total_ms: int


class TtsClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def synthesize(self, text: str, voice: Optional[str] = None) -> TtsResult:
        start = time.perf_counter()
        if self.settings.mock_mode:
            return TtsResult(audio=generate_tone_wav(), first_audio_ms=0, total_ms=0)
        payload = {
            "model": self.settings.tts_model,
            "input": text,
            "response_format": "wav",
        }
        selected_voice = voice or self.settings.voice_profile
        # OmniVoice rejects unknown profile names instead of falling back. Only send
        # a voice when the caller explicitly provides a supported preset/profile.
        if selected_voice and selected_voice.lower() not in {"default", "sylens"}:
            payload["voice"] = selected_voice
        async with httpx.AsyncClient(timeout=self.settings.request_timeout_s) as client:
            resp = await client.post(f"{self.settings.tts_url}/v1/audio/speech", json=payload)
            resp.raise_for_status()
            data = resp.content
        elapsed = int((time.perf_counter() - start) * 1000)
        return TtsResult(audio=data, first_audio_ms=elapsed, total_ms=elapsed)
