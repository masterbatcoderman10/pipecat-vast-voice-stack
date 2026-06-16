import asyncio
import pytest

from app.realtime.stt_stream import StreamingSttAdapter


@pytest.mark.asyncio
async def test_mock_streaming_stt_adapter_emits_partial_and_final():
    adapter = StreamingSttAdapter(mode="mock")

    partials = await adapter.feed_pcm(b"\x01\x00" * 320)
    assert [(item.text, item.is_final) for item in partials] == [("mock realtime", False)]

    assert await adapter.feed_pcm(b"\x01\x00" * 320) == []
    final = await adapter.commit()
    assert final.text == "mock realtime transcript"
    assert final.is_final is True


class FakeStreamingSocket:
    def __init__(self):
        self.sent = []
        self.recv_queue = ['{"type":"session.ready"}']

    async def send(self, payload):
        self.sent.append(payload)
        if isinstance(payload, bytes):
            self.recv_queue.append('{"type":"stt.partial","text":"hello","is_final":false}')
        elif payload == '{"type":"audio.input.commit"}':
            self.recv_queue.append('{"type":"stt.final","text":"hello world","is_final":true}')

    async def recv(self):
        while not self.recv_queue:
            await asyncio.sleep(0.01)
        return self.recv_queue.pop(0)

    async def close(self):
        self.sent.append("<closed>")


@pytest.mark.asyncio
async def test_live_streaming_stt_adapter_uses_stt_websocket_protocol():
    fake = FakeStreamingSocket()

    async def connect(url):
        assert url == "ws://127.0.0.1:9001/v1/audio/transcriptions/stream"
        return fake

    adapter = StreamingSttAdapter(mode="live", stt_url="http://127.0.0.1:9001", connect=connect)

    partials = await adapter.feed_pcm(b"\x01\x00" * 320)
    final = await adapter.commit()

    assert [item.text for item in partials] == ["hello"]
    assert final.text == "hello world"
    assert fake.sent[0].startswith('{"type":"session.start"')
    assert fake.sent[1] == b"\x01\x00" * 320
    assert fake.sent[2] == '{"type":"audio.input.commit"}'
