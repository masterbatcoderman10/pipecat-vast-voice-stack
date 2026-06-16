import pytest

from app.realtime.vad import EnergyVadAdapter, PipecatSileroVadAdapter


class FakeState:
    def __init__(self, name):
        self.name = name


class FakeAnalyzer:
    def __init__(self, states):
        self.states = list(states)

    async def analyze_audio(self, _pcm):
        return FakeState(self.states.pop(0))


@pytest.mark.asyncio
async def test_pipecat_silero_vad_adapter_maps_states_to_transitions():
    vad = PipecatSileroVadAdapter(analyzer=FakeAnalyzer(["STARTING", "SPEAKING", "QUIET"]))

    assert await vad.feed_pcm(b"\x01\x00" * 320) == ["speech_start"]
    assert await vad.feed_pcm(b"\x02\x00" * 320) == []
    assert await vad.feed_pcm(b"\x00\x00" * 320) == ["speech_stop"]


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
