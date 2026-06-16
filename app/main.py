from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response

from app.config import get_settings
from app.pipeline import VoicePipeline
from app.realtime.session import RealtimeSession
from app.utils.audio import normalize_audio_bytes

settings = get_settings()
app = FastAPI(title="Pipecat Vast Voice Stack", version="0.1.0")
pipeline = VoicePipeline(settings)


class ThinkFilter:
    def __init__(self):
        self.hidden = False
        self.buffer = ""

    def feed(self, token: str) -> str:
        self.buffer += token
        visible = []
        while self.buffer:
            if self.hidden:
                end = self.buffer.find("</think>")
                if end < 0:
                    self.buffer = ""
                    break
                self.buffer = self.buffer[end + len("</think>") :]
                self.hidden = False
                continue
            start = self.buffer.find("<think>")
            if start < 0:
                visible.append(self.buffer)
                self.buffer = ""
                break
            visible.append(self.buffer[:start])
            self.buffer = self.buffer[start + len("<think>") :]
            self.hidden = True
        return "".join(visible)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mock_mode": settings.mock_mode, "artifact_dir": str(settings.artifact_dir)}


@app.get("/health/realtime")
def realtime_health() -> dict:
    mode = "mock" if settings.mock_mode else "local"
    return {
        "status": "ok",
        "vad": "energy/mock" if settings.mock_mode else "pipecat/silero",
        "stt_streaming": "mock/local" if settings.mock_mode else "nemotron/ws-cache-aware",
        "llm_streaming": f"{mode}/local",
        "tts_streaming": "mock/sentence" if settings.mock_mode else "omnivoice/sentence-pcm",
        "audio_input": "pcm_s16le/16000/mono",
        "audio_output": "audio/wav/mock-tone" if settings.mock_mode else "audio/pcm;rate=24000;channels=1;encoding=pcm_s16le",
        "mock_mode": settings.mock_mode,
    }


@app.get("/v1/models")
def models() -> dict:
    return {
        "object": "list",
        "data": [
            {"id": settings.stt_model, "object": "model", "owned_by": "nvidia", "role": "stt"},
            {"id": settings.brain_served_model, "object": "model", "owned_by": "liquidai", "role": "brain"},
            {"id": settings.tts_model, "object": "model", "owned_by": "k2-fsa", "role": "tts"},
        ],
    }


@app.post("/v1/voice-turn")
async def voice_turn(
    file: UploadFile = File(...),
    prompt_preamble: Optional[str] = Form(default=None),
    voice: Optional[str] = Form(default=None),
    stream: bool = Form(default=False),
):
    wav_bytes = await file.read()
    try:
        result = await pipeline.run_turn(
            wav_bytes,
            filename=file.filename or "input.wav",
            prompt_preamble=prompt_preamble,
            voice=voice,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if stream:
        audio_path = settings.artifact_dir / Path(result["audio_url"]).name
        return Response(content=audio_path.read_bytes(), media_type="audio/wav")
    return result


@app.get("/artifacts/{name}")
def artifacts(name: str):
    if "/" in name or ".." in name:
        raise HTTPException(status_code=404, detail="not found")
    path = settings.artifact_dir / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type="audio/wav", filename=name)


@app.post("/v1/audio/transcriptions")
async def transcriptions_passthrough(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    result = await pipeline.stt.transcribe(data, filename=file.filename or "input.wav")
    return {"text": result.text}


@app.post("/v1/chat/completions")
async def chat_completions_passthrough(payload: dict) -> dict:
    messages = payload.get("messages", [])
    user_text = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")
    result = await pipeline.brain.complete(user_text)
    return {"choices": [{"message": {"role": "assistant", "content": result.text}}]}


@app.post("/v1/audio/speech")
async def speech_passthrough(payload: dict) -> Response:
    result = await pipeline.tts.synthesize(payload.get("input", ""), voice=payload.get("voice"))
    return Response(content=result.audio, media_type="audio/wav")


@app.websocket("/v2/realtime/ws")
async def realtime_ws(websocket: WebSocket):
    await RealtimeSession(websocket, settings).run()


@app.websocket("/v1/voice-turn/ws")
async def voice_turn_ws(websocket: WebSocket):
    await websocket.accept()
    total_start = time.perf_counter()
    try:
        start = json.loads(await websocket.receive_text())
        if start.get("type") != "start":
            await websocket.send_json({"type": "error", "message": "first message must be start"})
            return
        await websocket.send_json({"type": "ready"})

        audio = await websocket.receive_bytes()
        end = json.loads(await websocket.receive_text())
        if end.get("type") != "end":
            await websocket.send_json({"type": "error", "message": "expected end after audio bytes"})
            return

        await websocket.send_json({"type": "stt_start"})
        stt_start = time.perf_counter()
        normalized = normalize_audio_bytes(audio, mime_type=start.get("mime_type"))
        stt_result = await pipeline.stt.transcribe(normalized, filename="input.wav")
        stt_ms = int((time.perf_counter() - stt_start) * 1000)
        await websocket.send_json({"type": "transcript", "text": stt_result.text, "elapsed_ms": stt_ms})

        await websocket.send_json({"type": "llm_start"})
        llm_start = time.perf_counter()
        first_token_ms = None
        visible_chunks = []
        think_filter = ThinkFilter()
        async for token in pipeline.brain.stream_complete(stt_result.text, prompt_preamble=start.get("prompt_preamble")):
            visible_token = think_filter.feed(token)
            if not visible_token:
                continue
            if first_token_ms is None:
                first_token_ms = int((time.perf_counter() - llm_start) * 1000)
            visible_chunks.append(visible_token)
            await websocket.send_json({"type": "llm_token", "text": visible_token})
        assistant_text = "".join(visible_chunks).strip()
        llm_total_ms = int((time.perf_counter() - llm_start) * 1000)
        await websocket.send_json(
            {
                "type": "llm_done",
                "text": assistant_text,
                "first_token_ms": first_token_ms or llm_total_ms,
                "total_ms": llm_total_ms,
            }
        )

        await websocket.send_json({"type": "tts_start"})
        tts_result = await pipeline.tts.synthesize(assistant_text, voice=start.get("voice"))
        await websocket.send_json({"type": "audio_start", "mime_type": "audio/wav"})
        await websocket.send_bytes(tts_result.audio)
        await websocket.send_json({"type": "audio_done", "bytes": len(tts_result.audio), "elapsed_ms": tts_result.total_ms})

        await websocket.send_json(
            {
                "type": "done",
                "timings": {
                    "stt_ms": stt_ms,
                    "llm_first_token_ms": first_token_ms or llm_total_ms,
                    "llm_total_ms": llm_total_ms,
                    "tts_total_ms": tts_result.total_ms,
                    "total_ms": int((time.perf_counter() - total_start) * 1000),
                },
            }
        )
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
