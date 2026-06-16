from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol
from urllib.parse import urlparse, urlunparse


@dataclass
class SttResult:
    text: str
    is_final: bool


class StreamingSocket(Protocol):
    async def send(self, payload: str | bytes) -> None: ...
    async def recv(self) -> str | bytes: ...
    async def close(self) -> None: ...


ConnectFn = Callable[[str], Awaitable[StreamingSocket]]


def stt_stream_ws_url(stt_url: str) -> str:
    parsed = urlparse(stt_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, "/v1/audio/transcriptions/stream", "", "", ""))


async def default_connect(url: str) -> StreamingSocket:
    import websockets

    return await websockets.connect(url)  # type: ignore[return-value]


class StreamingSttAdapter:
    """Realtime STT facade.

    Mock mode is local/deterministic. Live mode speaks the Nemotron STT
    service's streaming WebSocket protocol and returns partial/final transcript
    events to the realtime session.
    """

    def __init__(
        self,
        *,
        mode: str = "mock",
        stt_url: str = "http://127.0.0.1:9001",
        sample_rate: int = 16_000,
        channels: int = 1,
        encoding: str = "pcm_s16le",
        connect: ConnectFn = default_connect,
    ):
        self.mode = mode
        self.stt_url = stt_url
        self.sample_rate = sample_rate
        self.channels = channels
        self.encoding = encoding
        self.connect = connect
        self._buffer = bytearray()
        self._partial_emitted = False
        self._socket: StreamingSocket | None = None
        self._ready = False

    async def feed_pcm(self, pcm: bytes) -> list[SttResult]:
        if pcm:
            self._buffer.extend(pcm)
        if self.mode == "mock":
            if self._buffer and not self._partial_emitted:
                self._partial_emitted = True
                return [SttResult(text="mock realtime", is_final=False)]
            return []

        await self._ensure_socket()
        assert self._socket is not None
        await self._socket.send(pcm)
        return await self._drain_until_timeout()

    async def commit(self) -> SttResult:
        if self.mode == "mock":
            text = "mock realtime transcript" if self._buffer else ""
            return SttResult(text=text, is_final=True)

        await self._ensure_socket()
        assert self._socket is not None
        await self._socket.send(json.dumps({"type": "audio.input.commit"}, separators=(",", ":")))
        while True:
            message = await self._socket.recv()
            event = self._parse_event(message)
            if event is None:
                continue
            if event.get("type") == "stt.final":
                return SttResult(text=str(event.get("text") or ""), is_final=True)
            if event.get("type") == "error":
                raise RuntimeError(str(event.get("message") or "streaming STT failed"))

    async def cancel(self) -> None:
        if self._socket is not None:
            await self._socket.send(json.dumps({"type": "response.cancel"}, separators=(",", ":")))
            await self._socket.close()
        self.reset()

    def reset(self) -> None:
        self._buffer.clear()
        self._partial_emitted = False
        self._socket = None
        self._ready = False

    async def _ensure_socket(self) -> None:
        if self._socket is not None and self._ready:
            return
        self._socket = await self.connect(stt_stream_ws_url(self.stt_url))
        await self._socket.send(
            json.dumps(
                {
                    "type": "session.start",
                    "sample_rate": self.sample_rate,
                    "channels": self.channels,
                    "encoding": self.encoding,
                },
                separators=(",", ":"),
            )
        )
        while True:
            message = await self._socket.recv()
            event = self._parse_event(message)
            if event is None:
                continue
            if event.get("type") == "session.ready":
                self._ready = True
                return
            if event.get("type") == "error":
                raise RuntimeError(str(event.get("message") or "streaming STT failed"))

    async def _drain_until_timeout(self) -> list[SttResult]:
        assert self._socket is not None
        results: list[SttResult] = []
        while True:
            try:
                message = await asyncio.wait_for(self._socket.recv(), timeout=0.001)
            except TimeoutError:
                return results
            event = self._parse_event(message)
            if event is None:
                continue
            if event.get("type") == "stt.partial":
                results.append(SttResult(text=str(event.get("text") or ""), is_final=False))
            elif event.get("type") == "stt.final":
                results.append(SttResult(text=str(event.get("text") or ""), is_final=True))
            elif event.get("type") == "error":
                raise RuntimeError(str(event.get("message") or "streaming STT failed"))

    @staticmethod
    def _parse_event(message: str | bytes) -> dict | None:
        if isinstance(message, bytes):
            return None
        return json.loads(message)
