from __future__ import annotations

import math
from typing import Any


class EnergyVadAdapter:
    """Small local int16 PCM energy VAD.

    It emits symbolic transition names so the websocket session can map them to
    protocol events without coupling this adapter to FastAPI.
    """

    def __init__(self, *, energy_threshold: int = 1, silence_frames: int = 3):
        self.energy_threshold = energy_threshold
        self.silence_frames = silence_frames
        self.in_speech = False
        self._silent_chunks = 0

    def feed_pcm(self, pcm: bytes) -> list[str]:
        if not pcm:
            return []
        usable = pcm[: len(pcm) - (len(pcm) % 2)]
        if not usable:
            return []
        samples = [int.from_bytes(usable[i : i + 2], "little", signed=True) for i in range(0, len(usable), 2)]
        energy = int(math.sqrt(sum(sample * sample for sample in samples) / len(samples)))
        events: list[str] = []
        if energy >= self.energy_threshold:
            self._silent_chunks = 0
            if not self.in_speech:
                self.in_speech = True
                events.append("speech_start")
            return events

        if self.in_speech:
            self._silent_chunks += 1
            if self._silent_chunks >= self.silence_frames:
                self.in_speech = False
                self._silent_chunks = 0
                events.append("speech_stop")
        return events

    def commit(self) -> list[str]:
        if not self.in_speech:
            self._silent_chunks = 0
            return []
        self.in_speech = False
        self._silent_chunks = 0
        return ["speech_stop"]

    def reset(self) -> None:
        self.in_speech = False
        self._silent_chunks = 0


class PipecatSileroVadAdapter:
    """Pipecat/Silero VAD adapter for live realtime sessions.

    This uses Pipecat's `SileroVADAnalyzer` directly while preserving the repo's
    websocket event contract (`speech_start` / `speech_stop`).
    """

    def __init__(self, *, sample_rate: int = 16_000, analyzer: Any | None = None):
        self.sample_rate = sample_rate
        self.in_speech = False
        if analyzer is not None:
            self.analyzer = analyzer
            self._vad_state = None
            return
        try:
            from pipecat.audio.vad.silero import SileroVADAnalyzer
            from pipecat.audio.vad.vad_analyzer import VADParams, VADState
        except Exception as exc:  # pragma: no cover - depends on image deps
            raise RuntimeError("Pipecat Silero VAD is not installed; install pipecat-ai[websocket]") from exc
        self._vad_state = VADState
        self.analyzer = SileroVADAnalyzer(
            sample_rate=sample_rate,
            params=VADParams(confidence=0.7, start_secs=0.2, stop_secs=0.2, min_volume=0.6),
        )

    async def feed_pcm(self, pcm: bytes) -> list[str]:
        if not pcm:
            return []
        state = await self.analyzer.analyze_audio(pcm)
        name = getattr(state, "name", str(state)).lower()
        events: list[str] = []
        if name in {"starting", "speaking"}:
            if not self.in_speech:
                self.in_speech = True
                events.append("speech_start")
        elif name in {"stopping", "quiet"} and self.in_speech:
            self.in_speech = False
            events.append("speech_stop")
        return events

    async def commit(self) -> list[str]:
        if not self.in_speech:
            return []
        self.in_speech = False
        return ["speech_stop"]

    def reset(self) -> None:
        self.in_speech = False


def create_vad_adapter(*, mock_mode: bool, sample_rate: int = 16_000):
    if mock_mode:
        return EnergyVadAdapter()
    return PipecatSileroVadAdapter(sample_rate=sample_rate)
