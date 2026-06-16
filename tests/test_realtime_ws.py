import importlib
import json

from fastapi.testclient import TestClient


def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_MODE", "1")
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    import app.main as main

    importlib.reload(main)
    return TestClient(main.app)


def test_realtime_websocket_mock_contract(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    start = {
        "type": "session.start",
        "session_id": "test-session",
        "sample_rate": 16000,
        "channels": 1,
        "encoding": "pcm_s16le",
        "voice": "clone:sylens",
    }

    with client.websocket_connect("/v2/realtime/ws") as ws:
        ws.send_text(json.dumps(start))
        first = ws.receive_json()
        assert first["type"] == "session.ready"
        assert first["session_id"] == "test-session"
        assert first["mode"] == "mock"

        for _ in range(3):
            ws.send_bytes(b"\x01\x00" * 320)
        ws.send_text(json.dumps({"type": "audio.input.commit"}))

        text_events = [first]
        binary_indices = []
        done_event = None
        while True:
            msg = ws.receive()
            if "text" in msg:
                event = json.loads(msg["text"])
                assert event["type"] != "error", event.get("message")
                text_events.append(event)
                if event["type"] == "response.done":
                    done_event = event
                    break
            elif "bytes" in msg:
                binary_indices.append(len(text_events))

    event_types = [event["type"] for event in text_events]
    assert event_types[:6] == [
        "session.ready",
        "vad.speech_start",
        "stt.partial",
        "vad.speech_stop",
        "stt.final",
        "llm.start",
    ]
    assert event_types.count("llm.token") > 2
    assert "llm.segment" in event_types
    assert event_types[-4:] == ["tts.start", "tts.audio_start", "tts.audio_done", "response.done"]

    audio_start_index = event_types.index("tts.audio_start") + 1
    done_index = event_types.index("response.done")
    assert any(audio_start_index <= idx < done_index for idx in binary_indices)

    assert done_event is not None
    assert "timings" in done_event
    assert "first_audio_ms" in done_event["timings"]
    assert isinstance(done_event["timings"]["first_audio_ms"], int)


def test_realtime_websocket_response_cancel(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    with client.websocket_connect("/v2/realtime/ws") as ws:
        ws.send_text(
            json.dumps(
                {
                    "type": "session.start",
                    "session_id": "cancel-session",
                    "sample_rate": 16000,
                    "channels": 1,
                    "encoding": "pcm_s16le",
                }
            )
        )
        assert ws.receive_json()["type"] == "session.ready"

        ws.send_bytes(b"\x01\x00" * 320)
        assert ws.receive_json()["type"] == "vad.speech_start"
        assert ws.receive_json()["type"] == "stt.partial"
        ws.send_text(json.dumps({"type": "response.cancel"}))

        cancelled = ws.receive_json()
        assert cancelled["type"] == "response.cancelled"
        assert cancelled["session_id"] == "cancel-session"


def test_realtime_health_contract(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    response = client.get("/health/realtime")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ok",
        "vad": "energy/mock",
        "stt_streaming": "mock/local",
        "llm_streaming": "mock/local",
        "tts_streaming": "mock/sentence",
        "audio_input": "pcm_s16le/16000/mono",
        "audio_output": "audio/wav/mock-tone",
        "mock_mode": True,
    }


def test_realtime_health_contract_live_tts_uses_omnivoice_pcm(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_MODE", "0")
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    import app.main as main

    importlib.reload(main)
    client = TestClient(main.app)

    response = client.get("/health/realtime")

    assert response.status_code == 200
    body = response.json()
    assert body["vad"] == "pipecat/silero"
    assert body["stt_streaming"] == "nemotron/ws-cache-aware"
    assert body["tts_streaming"] == "omnivoice/sentence-pcm"
    assert body["audio_output"] == "audio/pcm;rate=24000;channels=1;encoding=pcm_s16le"
    assert body["mock_mode"] is False
