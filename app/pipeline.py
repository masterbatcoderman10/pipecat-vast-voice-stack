from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Optional

from app.config import Settings
from app.services.brain_client import BrainClient
from app.services.stt_client import SttClient
from app.services.tts_client import TtsClient
from app.utils.audio import normalize_wav_bytes, write_wav_file


class VoicePipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.stt = SttClient(settings)
        self.brain = BrainClient(settings)
        self.tts = TtsClient(settings)

    async def run_turn(
        self,
        wav_bytes: bytes,
        filename: str = "input.wav",
        prompt_preamble: Optional[str] = None,
        voice: Optional[str] = None,
    ) -> dict:
        total_start = time.perf_counter()
        normalized = normalize_wav_bytes(wav_bytes)
        run_id = uuid.uuid4().hex
        artifact_dir = Path(self.settings.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        write_wav_file(artifact_dir / f"{run_id}.input.wav", normalized)

        stt_result = await self.stt.transcribe(normalized, filename=filename)
        brain_result = await self.brain.complete(stt_result.text, prompt_preamble=prompt_preamble)
        tts_result = await self.tts.synthesize(brain_result.text, voice=voice)
        output_name = f"{run_id}.wav"
        write_wav_file(artifact_dir / output_name, tts_result.audio)

        total_ms = int((time.perf_counter() - total_start) * 1000)
        return {
            "transcript": stt_result.text,
            "assistant_text": brain_result.text,
            "audio_format": "wav",
            "audio_url": f"/artifacts/{output_name}",
            "timings": {
                "stt_ms": stt_result.elapsed_ms,
                "llm_first_token_ms": brain_result.first_token_ms,
                "llm_total_ms": brain_result.total_ms,
                "tts_first_audio_ms": tts_result.first_audio_ms,
                "tts_total_ms": tts_result.total_ms,
                "total_ms": total_ms,
            },
        }
