import importlib
import json
import subprocess

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


def test_voice_turn_websocket_accepts_browser_webm_audio(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    wav_path = tmp_path / "sample.wav"
    webm_path = tmp_path / "recording.webm"
    wav_path.write_bytes(open("tests/fixtures/sample.wav", "rb").read())
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(wav_path),
            "-c:a",
            "libopus",
            str(webm_path),
        ],
        check=True,
    )
    webm = webm_path.read_bytes()
    assert not webm.startswith(b"RIFF")

    with client.websocket_connect("/v1/voice-turn/ws") as ws:
        ws.send_text(
            json.dumps(
                {
                    "type": "start",
                    "filename": "recording.webm",
                    "mime_type": "audio/webm;codecs=opus",
                    "voice": "default",
                }
            )
        )
        assert ws.receive_json()["type"] == "ready"
        ws.send_bytes(webm)
        ws.send_text(json.dumps({"type": "end"}))

        seen = []
        audio = None
        while True:
            msg = ws.receive()
            if "text" in msg:
                event = json.loads(msg["text"])
                assert event["type"] != "error", event.get("message")
                seen.append(event["type"])
                if event["type"] == "done":
                    break
            elif "bytes" in msg:
                audio = msg["bytes"]

    assert "transcript" in seen
    assert "llm_token" in seen
    assert audio is not None
    validate_wav_bytes(audio)
