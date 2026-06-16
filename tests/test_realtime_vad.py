from app.realtime.vad import EnergyVadAdapter


def test_energy_vad_starts_on_nonzero_pcm_and_stops_on_commit():
    vad = EnergyVadAdapter(energy_threshold=1, silence_frames=2)

    assert vad.feed_pcm(b"\x01\x00" * 320) == ["speech_start"]
    assert vad.feed_pcm(b"\x02\x00" * 320) == []
    assert vad.commit() == ["speech_stop"]


def test_energy_vad_silence_threshold_stops_speech():
    vad = EnergyVadAdapter(energy_threshold=10, silence_frames=2)

    assert vad.feed_pcm((100).to_bytes(2, "little", signed=True) * 320) == ["speech_start"]
    assert vad.feed_pcm(b"\x00\x00" * 320) == []
    assert vad.feed_pcm(b"\x00\x00" * 320) == ["speech_stop"]


def test_energy_vad_silence_does_not_start_speech():
    vad = EnergyVadAdapter(energy_threshold=1, silence_frames=1)

    assert vad.feed_pcm(b"\x00\x00" * 320) == []
    assert vad.commit() == []
