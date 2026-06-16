from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from app.config import get_settings
from app.pipeline import VoicePipeline

settings = get_settings()
app = FastAPI(title="Pipecat Vast Voice Stack", version="0.1.0")
pipeline = VoicePipeline(settings)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mock_mode": settings.mock_mode, "artifact_dir": str(settings.artifact_dir)}


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
