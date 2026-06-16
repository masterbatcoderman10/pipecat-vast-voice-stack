from __future__ import annotations

import json
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.config import Settings
from app.realtime.protocol import error, event
from app.utils.audio import generate_tone_wav


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
        self._speech_started = False
        self._audio_bytes = 0
        self._session_started_at = time.perf_counter()
        self._first_audio_ms: int | None = None

    async def run(self) -> None:
        await self.websocket.accept()
        try:
            start = json.loads(await self.websocket.receive_text())
            if start.get("type") != "session.start":
                await self.websocket.send_json(error("first message must be session.start"))
                return

            self._configure(start)
            if not self.settings.mock_mode:
                await self.websocket.send_json(
                    error(
                        "realtime live mode not implemented",
                        session_id=self.session_id,
                        mode="live",
                    )
                )
                return

            await self.websocket.send_json(event("session.ready", session_id=self.session_id, mode="mock"))
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
                if payload.get("type") == "audio.input.commit":
                    await self._handle_commit()
                    return
                await self.websocket.send_json(error(f"unexpected message type: {payload.get('type')}"))
                return
            if message.get("type") == "websocket.disconnect":
                return

    async def _handle_audio(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._audio_bytes += len(chunk)
        if not self._speech_started:
            self._speech_started = True
            await self.websocket.send_json(
                event(
                    "vad.speech_start",
                    session_id=self.session_id,
                    audio_bytes=self._audio_bytes,
                )
            )

    async def _handle_commit(self) -> None:
        if self._speech_started:
            await self.websocket.send_json(event("vad.speech_stop", session_id=self.session_id, audio_bytes=self._audio_bytes))

        transcript = "mock realtime transcript"
        response_text = "Mock realtime response."
        await self.websocket.send_json(event("stt.final", session_id=self.session_id, text=transcript))
        await self.websocket.send_json(event("llm.start", session_id=self.session_id))
        await self.websocket.send_json(event("llm.token", session_id=self.session_id, text=response_text))
        await self.websocket.send_json(event("llm.segment", session_id=self.session_id, text=response_text))
        await self.websocket.send_json(event("tts.start", session_id=self.session_id, voice=self.voice))

        audio = generate_tone_wav(duration_s=0.1, sample_rate=self.sample_rate)
        self._first_audio_ms = int((time.perf_counter() - self._session_started_at) * 1000)
        await self.websocket.send_json(
            event("tts.audio_start", session_id=self.session_id, mime_type="audio/wav", encoding="wav")
        )
        await self.websocket.send_bytes(audio)
        await self.websocket.send_json(event("tts.audio_done", session_id=self.session_id, bytes=len(audio)))
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
