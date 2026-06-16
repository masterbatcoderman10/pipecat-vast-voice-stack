from __future__ import annotations

import io
import math
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Union

DEFAULT_SAMPLE_RATE = 16_000


class AudioError(ValueError):
    pass


def generate_silence_wav(duration_s: float = 0.25, sample_rate: int = DEFAULT_SAMPLE_RATE) -> bytes:
    frames = max(1, int(duration_s * sample_rate))
    with io.BytesIO() as buf:
        with wave.open(buf, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(b"\x00\x00" * frames)
        return buf.getvalue()


def generate_tone_wav(duration_s: float = 0.35, sample_rate: int = DEFAULT_SAMPLE_RATE, freq: float = 440.0) -> bytes:
    frames = max(1, int(duration_s * sample_rate))
    pcm = bytearray()
    for i in range(frames):
        value = int(0.15 * 32767 * math.sin(2 * math.pi * freq * i / sample_rate))
        pcm.extend(value.to_bytes(2, "little", signed=True))
    with io.BytesIO() as buf:
        with wave.open(buf, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(bytes(pcm))
        return buf.getvalue()


def validate_wav_bytes(data: bytes) -> dict[str, int | float]:
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            channels = wav.getnchannels()
            sample_rate = wav.getframerate()
            sample_width = wav.getsampwidth()
            frames = wav.getnframes()
    except wave.Error as exc:
        raise AudioError(f"invalid wav: {exc}") from exc
    if channels < 1:
        raise AudioError("invalid wav: no channels")
    if sample_width not in (1, 2, 3, 4):
        raise AudioError(f"unsupported sample width: {sample_width}")
    return {
        "channels": channels,
        "sample_rate": sample_rate,
        "sample_width": sample_width,
        "frames": frames,
        "duration_s": frames / sample_rate if sample_rate else 0.0,
    }


def write_wav_file(path: Union[str, Path], data: bytes) -> Path:
    validate_wav_bytes(data)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def read_wav_file(path: Union[str, Path]) -> bytes:
    data = Path(path).read_bytes()
    validate_wav_bytes(data)
    return data


def normalize_wav_bytes(data: bytes) -> bytes:
    """Validate WAV and return bytes."""
    validate_wav_bytes(data)
    return data


def normalize_audio_bytes(data: bytes, *, mime_type: str | None = None) -> bytes:
    """Return STT-safe 16k mono WAV bytes for browser or WAV input.

    Browser MediaRecorder usually emits WebM/Opus, not RIFF/WAV. Keep the
    existing fast path for WAV and use ffmpeg only when the payload is another
    container/codec.
    """
    if data.startswith(b"RIFF"):
        return normalize_wav_bytes(data)

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AudioError("ffmpeg is required to transcode browser audio to wav")

    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-ac",
            "1",
            "-ar",
            str(DEFAULT_SAMPLE_RATE),
            "-f",
            "wav",
            "pipe:1",
        ],
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip() or "unknown ffmpeg error"
        suffix = f" ({mime_type})" if mime_type else ""
        raise AudioError(f"could not transcode audio{suffix}: {detail}")
    validate_wav_bytes(proc.stdout)
    return proc.stdout
