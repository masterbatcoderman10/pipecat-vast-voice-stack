from __future__ import annotations

import json
import os
import tempfile
import wave
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect

app = FastAPI(title="Nemotron STT Adapter", version="0.2.0")
_model = None
_model_error: Optional[str] = None


def mock_mode() -> bool:
    return os.getenv("MOCK_MODE", "0").lower() in {"1", "true", "yes", "on"}


def get_model():
    global _model, _model_error
    if mock_mode():
        return None
    if _model is not None:
        return _model
    try:
        # Deliberately imported lazily so local tests and CPU mock containers do not
        # need NeMo/CUDA installed.
        import nemo.collections.asr as nemo_asr  # type: ignore

        model_name = os.getenv("STT_MODEL", "nvidia/nemotron-speech-streaming-en-0.6b")
        _model = nemo_asr.models.ASRModel.from_pretrained(model_name=model_name)
        return _model
    except Exception as exc:  # pragma: no cover - exercised on GPU host only
        _model_error = str(exc)
        raise


def _pcm_to_wav_path(pcm: bytes, *, sample_rate: int, channels: int) -> Path:
    fd, name = tempfile.mkstemp(suffix=".wav", prefix="nemotron-stream-")
    os.close(fd)
    path = Path(name)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return path


def _result_text(result) -> str:
    first = result[0] if result else ""
    text = getattr(first, "text", first)
    return str(text)


def _transcribe_pcm_with_nemotron(pcm: bytes, *, sample_rate: int, channels: int) -> str:
    """Transcribe accumulated streaming PCM with the loaded Nemotron model.

    Nemotron is a cache-aware streaming RNNT model. The public NeMo entrypoint for
    local use is currently file/pipeline based, so this server exposes a real
    streaming transport and keeps audio in PCM chunks while preserving the option
    to use model-level cache-aware methods when available on the loaded class.
    """
    if not pcm:
        return ""
    model = get_model()

    if model is None:
        raise RuntimeError("Nemotron model is not loaded")

    # Some NeMo cache-aware models expose streaming helper methods. Prefer them
    # when present; fall back to transcribe() for compatibility with checkpoint
    # class/version differences on GPU hosts.
    for method_name in (
        "transcribe_streaming",
        "transcribe_simulate_cache_aware_streaming",
        "transcribe_cache_aware_streaming",
    ):
        method = getattr(model, method_name, None)
        if callable(method):  # pragma: no cover - depends on GPU NeMo version
            try:
                path = _pcm_to_wav_path(pcm, sample_rate=sample_rate, channels=channels)
                try:
                    return _result_text(method([str(path)]))
                finally:
                    path.unlink(missing_ok=True)
            except TypeError:
                continue

    path = _pcm_to_wav_path(pcm, sample_rate=sample_rate, channels=channels)
    try:
        return _result_text(model.transcribe([str(path)]))  # pragma: no cover
    finally:
        path.unlink(missing_ok=True)


@app.get("/health")
def health() -> dict:
    loaded = _model is not None or mock_mode()
    return {
        "status": "ok" if loaded or _model_error is None else "error",
        "mock_mode": mock_mode(),
        "model_loaded": loaded,
        "streaming_endpoint": "/v1/audio/transcriptions/stream",
        "streaming_model": "nemotron/cache-aware-rnnt",
        "error": _model_error,
    }


@app.post("/v1/audio/transcriptions")
async def transcribe(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    if mock_mode():
        return {"text": "mock nemotron transcript"}
    tmp = Path("/tmp") / (file.filename or "input.wav")
    tmp.write_bytes(data)
    model = get_model()
    result = model.transcribe([str(tmp)])  # pragma: no cover
    return {"text": _result_text(result)}  # pragma: no cover


@app.websocket("/v1/audio/transcriptions/stream")
async def transcribe_stream(websocket: WebSocket):
    await websocket.accept()
    sample_rate = 16_000
    channels = 1
    encoding = "pcm_s16le"
    buffer = bytearray()
    partial_emitted = False
    try:
        start = json.loads(await websocket.receive_text())
        if start.get("type") != "session.start":
            await websocket.send_json({"type": "error", "message": "first message must be session.start"})
            return
        sample_rate = int(start.get("sample_rate") or sample_rate)
        channels = int(start.get("channels") or channels)
        encoding = str(start.get("encoding") or encoding)
        if encoding != "pcm_s16le" or channels != 1:
            await websocket.send_json({"type": "error", "message": "expected pcm_s16le mono audio"})
            return
        await websocket.send_json(
            {
                "type": "session.ready",
                "sample_rate": sample_rate,
                "channels": channels,
                "encoding": encoding,
                "mode": "mock" if mock_mode() else "nemotron/cache-aware-rnnt",
            }
        )

        while True:
            message = await websocket.receive()
            if "bytes" in message:
                chunk = message["bytes"] or b""
                if not chunk:
                    continue
                buffer.extend(chunk)
                if mock_mode() and not partial_emitted:
                    partial_emitted = True
                    await websocket.send_json(
                        {"type": "stt.partial", "text": "mock nemotron streaming", "is_final": False}
                    )
                elif not mock_mode() and len(buffer) >= sample_rate * 2:  # ~1s of mono PCM16
                    text = _transcribe_pcm_with_nemotron(bytes(buffer), sample_rate=sample_rate, channels=channels)
                    if text:
                        await websocket.send_json({"type": "stt.partial", "text": text, "is_final": False})
                continue

            if "text" in message:
                payload = json.loads(message["text"])
                if payload.get("type") == "response.cancel":
                    buffer.clear()
                    await websocket.send_json({"type": "response.cancelled"})
                    return
                if payload.get("type") == "audio.input.commit":
                    text = (
                        "mock nemotron streaming transcript"
                        if mock_mode() and buffer
                        else _transcribe_pcm_with_nemotron(bytes(buffer), sample_rate=sample_rate, channels=channels)
                    )
                    await websocket.send_json({"type": "stt.final", "text": text, "is_final": True})
                    return
                await websocket.send_json({"type": "error", "message": f"unexpected message type: {payload.get('type')}"})
                return

            if message.get("type") == "websocket.disconnect":
                return
    except WebSocketDisconnect:
        return
    except Exception as exc:  # pragma: no cover - live GPU only
        await websocket.send_json({"type": "error", "message": str(exc)})
