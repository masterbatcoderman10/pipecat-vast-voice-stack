from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SttResult:
    text: str
    is_final: bool


class StreamingSttAdapter:
    """Mock/local streaming STT facade.

    The mock implementation buffers PCM and emits deterministic partial/final
    transcripts without external service calls. Live mode intentionally keeps the
    same local turn-final placeholder shape for future service wiring.
    """

    def __init__(self, *, mode: str = "mock"):
        self.mode = mode
        self._buffer = bytearray()
        self._partial_emitted = False

    def feed_pcm(self, pcm: bytes) -> list[SttResult]:
        if pcm:
            self._buffer.extend(pcm)
        if self._buffer and not self._partial_emitted:
            self._partial_emitted = True
            return [SttResult(text="mock realtime", is_final=False)]
        return []

    def commit(self) -> SttResult:
        text = "mock realtime transcript" if self.mode == "mock" else "local realtime transcript"
        if not self._buffer:
            text = ""
        return SttResult(text=text, is_final=True)

    def reset(self) -> None:
        self._buffer.clear()
        self._partial_emitted = False
