import pytest

from app.realtime.tts_stream import StreamingTtsAdapter


@pytest.mark.asyncio
async def test_streaming_tts_adapter_yields_events_and_audio_for_each_segment():
    adapter = StreamingTtsAdapter(sample_rate=16000, voice="clone:sylens", mode="mock")

    items = []
    async for item in adapter.stream(["First sentence.", "Second sentence."]):
        items.append(item)

    assert items[0] == {"type": "tts.start", "voice": "clone:sylens"}
    assert items[1]["type"] == "tts.audio_start"
    assert items[1]["segment_index"] == 0
    assert isinstance(items[2], bytes)
    assert items[2].startswith(b"RIFF")
    assert items[3]["type"] == "tts.audio_done"
    assert items[4]["type"] == "tts.audio_start"
    assert items[4]["segment_index"] == 1
    assert isinstance(items[5], bytes)
    assert items[6]["type"] == "tts.audio_done"
    assert len([item for item in items if isinstance(item, bytes)]) == 2
