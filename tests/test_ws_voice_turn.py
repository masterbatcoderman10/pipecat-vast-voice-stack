import importlib
import json

from fastapi.testclient import TestClient

from app.main import ThinkFilter
from app.utils.audio import validate_wav_bytes


def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_MODE", "1")
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    import app.main as main
    importlib.reload(main)
    return TestClient(main.app)


def test_think_filter_hides_reasoning():
    f = ThinkFilter()
    assert f.feed("<think>") == ""
    assert f.feed("private") == ""
    assert f.feed("</think>Hi") == "Hi"
    assert f.feed(" there") == " there"


def test_voice_turn_websocket_contract(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    wav = open("tests/fixtures/sample.wav", "rb").read()

    with client.websocket_connect("/v1/voice-turn/ws") as ws:
        ws.send_text(json.dumps({"type": "start", "filename": "sample.wav", "voice": "default"}))
        assert ws.receive_json()["type"] == "ready"
        ws.send_bytes(wav)
        ws.send_text(json.dumps({"type": "end"}))

        seen = []
        audio = None
        while True:
            msg = ws.receive()
            if "text" in msg:
                event = json.loads(msg["text"])
                seen.append(event["type"])
                if event["type"] == "done":
                    break
            elif "bytes" in msg:
                audio = msg["bytes"]

    assert "transcript" in seen
    assert "llm_token" in seen
    assert "llm_done" in seen
    assert "audio_start" in seen
    assert "audio_done" in seen
    assert audio is not None
    validate_wav_bytes(audio)
