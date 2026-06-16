from __future__ import annotations

import inspect
import json
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.config import Settings
from app.realtime.protocol import error, event
from app.realtime.stt_stream import StreamingSttAdapter
from app.realtime.text_segmenter import TextSegmenter
from app.realtime.tts_stream import StreamingTtsAdapter
from app.realtime.vad import create_vad_adapter
from app.services.brain_client import BrainClient


class RealtimeSession:
    """Realtime websocket session handler.

    Task 2 intentionally implements deterministic mock-mode behavior only. Live
    mode is acknowledged with a protocol error and left for the Pipecat-backed
    implementation.
    """

    def __init__(self, websocket: WebSocket, settings: Settings):
        self.websocket = websocket
        self.settings = settings
        self.session_id = ""
        self.sample_rate = 16_000
        self.channels = 1
        self.encoding = "pcm_s16le"
        self.voice: str | None = None
        self._audio_bytes = 0
        self._session_started_at = time.perf_counter()
        self._first_audio_ms: int | None = None
        self.vad = create_vad_adapter(mock_mode=settings.mock_mode, sample_rate=self.sample_rate)
        stt_mode = "mock" if settings.mock_mode else "live"
        self.stt = StreamingSttAdapter(mode=stt_mode, stt_url=settings.stt_url)
        self.brain = BrainClient(settings)

    async def run(self) -> None:
        await self.websocket.accept()
        try:
            start = json.loads(await self.websocket.receive_text())
            if start.get("type") != "session.start":
                await self.websocket.send_json(error("first message must be session.start"))
                return

            self._configure(start)
            mode = "mock" if self.settings.mock_mode else "live"
            await self.websocket.send_json(event("session.ready", session_id=self.session_id, mode=mode))
            await self._run_mock_loop()
        except WebSocketDisconnect:
            return
        except Exception as exc:
            await self.websocket.send_json(error(str(exc), session_id=self.session_id or None))

    def _configure(self, start: dict[str, Any]) -> None:
        self.session_id = str(start.get("session_id") or "mock-session")
        self.sample_rate = int(start.get("sample_rate") or self.sample_rate)
        self.channels = int(start.get("channels") or self.channels)
        self.encoding = str(start.get("encoding") or self.encoding)
        self.voice = start.get("voice")

    async def _run_mock_loop(self) -> None:
        while True:
            message = await self.websocket.receive()
            if "bytes" in message:
                await self._handle_audio(message["bytes"])
                continue
            if "text" in message:
                payload = json.loads(message["text"])
                if payload.get("type") == "response.cancel":
                    await self._handle_cancel()
                    return
                if payload.get("type") == "audio.input.commit":
                    await self._handle_commit()
                    return
                await self.websocket.send_json(error(f"unexpected message type: {payload.get('type')}"))
                return
            if message.get("type") == "websocket.disconnect":
                return

    @staticmethod
    async def _maybe_await(value):
        if inspect.isawaitable(value):
            return await value
        return value

    async def _handle_audio(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._audio_bytes += len(chunk)
        for vad_event in await self._maybe_await(self.vad.feed_pcm(chunk)):
            await self.websocket.send_json(
                event(f"vad.{vad_event}", session_id=self.session_id, audio_bytes=self._audio_bytes)
            )
        for partial in await self.stt.feed_pcm(chunk):
            await self.websocket.send_json(
                event(
                    "stt.final" if partial.is_final else "stt.partial",
                    session_id=self.session_id,
                    text=partial.text,
                )
            )

    async def _handle_commit(self) -> None:
        for vad_event in await self._maybe_await(self.vad.commit()):
            await self.websocket.send_json(
                event(f"vad.{vad_event}", session_id=self.session_id, audio_bytes=self._audio_bytes)
            )

        transcript = (await self.stt.commit()).text
        await self.websocket.send_json(event("stt.final", session_id=self.session_id, text=transcript))
        await self.websocket.send_json(event("llm.start", session_id=self.session_id))

        segmenter = TextSegmenter(max_chars=80)
        segments: list[str] = []
        async for token in self.brain.stream_complete(transcript, prompt_preamble="Reply briefly and conversationally."):
            await self.websocket.send_json(event("llm.token", session_id=self.session_id, text=token))
            for segment in segmenter.feed(token):
                segments.append(segment)
                await self.websocket.send_json(event("llm.segment", session_id=self.session_id, text=segment))
        for segment in segmenter.flush():
            segments.append(segment)
            await self.websocket.send_json(event("llm.segment", session_id=self.session_id, text=segment))

        tts_mode = "mock" if self.settings.mock_mode else "omnivoice"
        tts = StreamingTtsAdapter(
            sample_rate=self.sample_rate,
            voice=self.voice,
            mode=tts_mode,
            tts_url=self.settings.tts_url,
            model=self.settings.tts_model,
            timeout_s=self.settings.request_timeout_s,
        )
        async for item in tts.stream(segments):
            if isinstance(item, bytes):
                if self._first_audio_ms is None:
                    self._first_audio_ms = int((time.perf_counter() - self._session_started_at) * 1000)
                await self.websocket.send_bytes(item)
                continue
            payload = {**item, "session_id": self.session_id}
            await self.websocket.send_json(payload)
        await self.websocket.send_json(
            event(
                "response.done",
                session_id=self.session_id,
                timings={
                    "first_audio_ms": self._first_audio_ms,
                    "total_ms": int((time.perf_counter() - self._session_started_at) * 1000),
                },
            )
        )

    async def _handle_cancel(self) -> None:
        self.vad.reset()
        await self.stt.cancel()
        await self.websocket.send_json(event("response.cancelled", session_id=self.session_id))
