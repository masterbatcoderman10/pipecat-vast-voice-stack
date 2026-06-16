from __future__ import annotations

import math


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
