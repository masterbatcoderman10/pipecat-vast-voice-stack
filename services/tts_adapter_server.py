from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import Response

from app.utils.audio import generate_tone_wav

app = FastAPI(title="Mock TTS Adapter", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "adapter": "mock-omnivoice-compatible"}


@app.post("/v1/audio/speech")
def speech(payload: dict) -> Response:
    # Placeholder OpenAI-style adapter. Replace internals with omnivoice-server
    # contract once validated on the target GPU image.
    return Response(content=generate_tone_wav(), media_type="audio/wav")
