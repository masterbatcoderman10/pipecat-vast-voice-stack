from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from app.config import Settings


@dataclass
class SttResult:
    text: str
    elapsed_ms: int


class SttClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def transcribe(self, wav_bytes: bytes, filename: str = "input.wav") -> SttResult:
        start = time.perf_counter()
        if self.settings.mock_mode:
            return SttResult(text="mock transcript from uploaded audio", elapsed_ms=0)
        async with httpx.AsyncClient(timeout=self.settings.request_timeout_s) as client:
            files = {"file": (filename, wav_bytes, "audio/wav")}
            resp = await client.post(f"{self.settings.stt_url}/v1/audio/transcriptions", files=files)
            resp.raise_for_status()
            payload = resp.json()
        return SttResult(text=payload.get("text", ""), elapsed_ms=int((time.perf_counter() - start) * 1000))
