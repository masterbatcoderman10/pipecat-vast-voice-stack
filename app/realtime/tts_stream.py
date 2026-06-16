from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from typing import Any

from app.utils.audio import generate_tone_wav


class StreamingTtsAdapter:
    """Local sentence TTS streamer.

    In mock/sentence mode each text segment becomes a tiny deterministic WAV tone
    chunk. The iterator yields protocol-shaped event dicts and raw audio bytes.
    """

    def __init__(self, *, sample_rate: int = 16_000, voice: str | None = None, mode: str = "mock"):
        self.sample_rate = sample_rate
        self.voice = voice
        self.mode = mode

    async def stream(self, segments: Iterable[str]) -> AsyncIterator[dict[str, Any] | bytes]:
        yield {"type": "tts.start", "voice": self.voice}
        for index, segment in enumerate(segments):
            text = segment.strip()
            if not text:
                continue
            yield {
                "type": "tts.audio_start",
                "mime_type": "audio/wav",
                "encoding": "wav",
                "segment_index": index,
                "text": text,
            }
            audio = generate_tone_wav(duration_s=0.1, sample_rate=self.sample_rate, freq=440.0 + (index * 30.0))
            yield audio
            yield {"type": "tts.audio_done", "bytes": len(audio), "segment_index": index}
