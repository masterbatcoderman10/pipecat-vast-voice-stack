import pytest

from app.utils.audio import AudioError, generate_silence_wav, generate_tone_wav, normalize_wav_bytes, validate_wav_bytes


def test_generate_and_validate_tone_wav():
    data = generate_tone_wav(duration_s=0.1)
    meta = validate_wav_bytes(data)
    assert meta["sample_rate"] == 16000
    assert meta["channels"] == 1
    assert meta["duration_s"] > 0


def test_normalize_validates_wav():
    data = generate_silence_wav()
    assert normalize_wav_bytes(data) == data
    with pytest.raises(AudioError):
        normalize_wav_bytes(b"not a wav")
