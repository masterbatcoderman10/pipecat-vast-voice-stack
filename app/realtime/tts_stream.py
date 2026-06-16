from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterable
from typing import Any

import httpx

from app.utils.audio import generate_tone_wav


class StreamingTtsAdapter:
    """Sentence TTS streamer.

    Mock mode emits deterministic WAV tones for local tests. OmniVoice mode uses
    omnivoice-server's native sentence-level HTTP chunked PCM path:
    `stream=true` + `response_format=pcm`.
    """

    def __init__(
        self,
        *,
        sample_rate: int = 16_000,
        voice: str | None = None,
        mode: str = "mock",
        tts_url: str = "http://127.0.0.1:9003",
        model: str = "k2-fsa/OmniVoice",
        timeout_s: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.sample_rate = sample_rate
        self.voice = voice
        self.mode = mode
        self.tts_url = tts_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.transport = transport

    async def stream(self, segments: Iterable[str]) -> AsyncIterator[dict[str, Any] | bytes]:
        if self.mode == "omnivoice":
            async for item in self._stream_omnivoice(segments):
                yield item
            return

        async for item in self._stream_mock(segments):
            yield item

    async def _stream_mock(self, segments: Iterable[str]) -> AsyncIterator[dict[str, Any] | bytes]:
        yield {"type": "tts.start", "voice": self.voice, "mode": "mock"}
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

    async def _stream_omnivoice(self, segments: Iterable[str]) -> AsyncIterator[dict[str, Any] | bytes]:
        yield {"type": "tts.start", "voice": self.voice, "mode": "omnivoice/sentence-pcm"}
        timeout = httpx.Timeout(self.timeout_s) if self.timeout_s else None
        async with httpx.AsyncClient(timeout=timeout, transport=self.transport) as client:
            for index, segment in enumerate(segments):
                text = segment.strip()
                if not text:
                    continue
                payload: dict[str, Any] = {
                    "model": self.model,
                    "input": text,
                    "response_format": "pcm",
                    "stream": True,
                }
                if self.voice:
                    payload["voice"] = self.voice

                start = time.perf_counter()
                byte_count = 0
                async with client.stream("POST", f"{self.tts_url}/v1/audio/speech", json=payload) as response:
                    response.raise_for_status()
                    sample_rate = int(response.headers.get("x-audio-sample-rate", "24000"))
                    channels = int(response.headers.get("x-audio-channels", "1"))
                    bit_depth = int(response.headers.get("x-audio-bit-depth", "16"))
                    audio_format = response.headers.get("x-audio-format", "pcm-int16-le")
                    encoding = "pcm_s16le" if audio_format == "pcm-int16-le" else audio_format
                    yield {
                        "type": "tts.audio_start",
                        "mime_type": response.headers.get("content-type", "audio/pcm").split(";", 1)[0],
                        "encoding": encoding,
                        "sample_rate": sample_rate,
                        "channels": channels,
                        "bit_depth": bit_depth,
                        "segment_index": index,
                        "text": text,
                    }
                    async for chunk in response.aiter_bytes():
                        if not chunk:
                            continue
                        byte_count += len(chunk)
                        yield chunk
                yield {
                    "type": "tts.audio_done",
                    "bytes": byte_count,
                    "segment_index": index,
                    "elapsed_ms": int((time.perf_counter() - start) * 1000),
                }
