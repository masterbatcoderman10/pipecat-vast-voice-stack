import httpx
import pytest

from app.realtime.tts_stream import StreamingTtsAdapter


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


@pytest.mark.asyncio
async def test_streaming_tts_adapter_yields_events_and_audio_for_each_segment():
    adapter = StreamingTtsAdapter(sample_rate=16000, voice="clone:sylens", mode="mock")

    items = []
    async for item in adapter.stream(["First sentence.", "Second sentence."]):
        items.append(item)

    assert items[0] == {"type": "tts.start", "voice": "clone:sylens", "mode": "mock"}
    assert items[1]["type"] == "tts.audio_start"
    assert items[1]["segment_index"] == 0
    assert items[1]["encoding"] == "wav"
    assert isinstance(items[2], bytes)
    assert items[2].startswith(b"RIFF")
    assert items[3]["type"] == "tts.audio_done"
    assert items[4]["type"] == "tts.audio_start"
    assert items[4]["segment_index"] == 1
    assert isinstance(items[5], bytes)
    assert items[6]["type"] == "tts.audio_done"
    assert len([item for item in items if isinstance(item, bytes)]) == 2


@pytest.mark.asyncio
async def test_omnivoice_streaming_adapter_requests_pcm_chunks_per_segment():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={
                "content-type": "audio/pcm",
                "x-audio-sample-rate": "24000",
                "x-audio-channels": "1",
                "x-audio-bit-depth": "16",
                "x-audio-format": "pcm-int16-le",
            },
            stream=ChunkStream([b"pcm-a", b"pcm-b"]),
        )

    transport = httpx.MockTransport(handler)
    adapter = StreamingTtsAdapter(
        voice="clone:sylens",
        mode="omnivoice",
        tts_url="http://omnivoice.test",
        model="k2-fsa/OmniVoice",
        transport=transport,
    )

    items = []
    async for item in adapter.stream(["Hello there."]):
        items.append(item)

    assert items[0] == {"type": "tts.start", "voice": "clone:sylens", "mode": "omnivoice/sentence-pcm"}
    assert items[1] == {
        "type": "tts.audio_start",
        "mime_type": "audio/pcm",
        "encoding": "pcm_s16le",
        "sample_rate": 24000,
        "channels": 1,
        "bit_depth": 16,
        "segment_index": 0,
        "text": "Hello there.",
    }
    assert items[2] == b"pcm-a"
    assert items[3] == b"pcm-b"
    assert items[4]["type"] == "tts.audio_done"
    assert items[4]["bytes"] == 10
    assert items[4]["segment_index"] == 0
    assert isinstance(items[4]["elapsed_ms"], int)

    assert len(requests) == 1
    assert requests[0].url == "http://omnivoice.test/v1/audio/speech"
    assert requests[0].headers["content-type"] == "application/json"
    body = __import__("json").loads(requests[0].content)
    assert body == {
        "model": "k2-fsa/OmniVoice",
        "input": "Hello there.",
        "voice": "clone:sylens",
        "response_format": "pcm",
        "stream": True,
    }
