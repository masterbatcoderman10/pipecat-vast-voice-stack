from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile

app = FastAPI(title="Nemotron STT Adapter", version="0.1.0")
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


@app.get("/health")
def health() -> dict:
    loaded = _model is not None or mock_mode()
    return {"status": "ok" if loaded or _model_error is None else "error", "mock_mode": mock_mode(), "model_loaded": loaded, "error": _model_error}


@app.post("/v1/audio/transcriptions")
async def transcribe(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    if mock_mode():
        return {"text": "mock nemotron transcript"}
    tmp = Path("/tmp") / (file.filename or "input.wav")
    tmp.write_bytes(data)
    model = get_model()
    # NeMo ASR models generally accept a list of file paths and return strings or
    # Hypothesis objects. Keep this tolerant for model-version variation.
    result = model.transcribe([str(tmp)])  # pragma: no cover
    first = result[0] if result else ""  # pragma: no cover
    text = getattr(first, "text", first)  # pragma: no cover
    return {"text": str(text)}  # pragma: no cover
