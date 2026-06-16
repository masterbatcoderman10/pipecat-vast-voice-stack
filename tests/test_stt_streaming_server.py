import importlib
import json

from fastapi.testclient import TestClient


def make_stt_client(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "1")
    import services.stt_nemotron_server as stt_server

    importlib.reload(stt_server)
    return TestClient(stt_server.app)


def test_stt_streaming_websocket_mock_partial_and_final(monkeypatch):
    client = make_stt_client(monkeypatch)

    with client.websocket_connect("/v1/audio/transcriptions/stream") as ws:
        ws.send_text(json.dumps({"type": "session.start", "sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le"}))
        assert ws.receive_json() == {"type": "session.ready", "sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le", "mode": "mock"}

        ws.send_bytes(b"\x01\x00" * 640)
        partial = ws.receive_json()
        assert partial["type"] == "stt.partial"
        assert partial["text"] == "mock nemotron streaming"
        assert partial["is_final"] is False

        ws.send_text(json.dumps({"type": "audio.input.commit"}))
        final = ws.receive_json()
        assert final["type"] == "stt.final"
        assert final["text"] == "mock nemotron streaming transcript"
        assert final["is_final"] is True


def test_stt_streaming_websocket_cancel(monkeypatch):
    client = make_stt_client(monkeypatch)

    with client.websocket_connect("/v1/audio/transcriptions/stream") as ws:
        ws.send_text(json.dumps({"type": "session.start"}))
        assert ws.receive_json()["type"] == "session.ready"
        ws.send_bytes(b"\x01\x00" * 320)
        assert ws.receive_json()["type"] == "stt.partial"
        ws.send_text(json.dumps({"type": "response.cancel"}))
        assert ws.receive_json() == {"type": "response.cancelled"}
