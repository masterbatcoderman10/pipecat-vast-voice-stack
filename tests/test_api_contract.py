import importlib

from fastapi.testclient import TestClient

from app.utils.audio import validate_wav_bytes


def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_MODE", "1")
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    import app.main as main
    importlib.reload(main)
    return TestClient(main.app)


def test_health_and_models(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["mock_mode"] is True
    models = client.get("/v1/models")
    assert models.status_code == 200
    roles = {m["role"] for m in models.json()["data"]}
    assert roles == {"stt", "brain", "tts"}


def test_voice_turn_contract(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    wav = open("tests/fixtures/sample.wav", "rb").read()
    response = client.post(
        "/v1/voice-turn",
        files={"file": ("sample.wav", wav, "audio/wav")},
        data={"prompt_preamble": "test", "voice": "default", "stream": "false"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["transcript"]
    assert payload["assistant_text"]
    assert payload["audio_format"] == "wav"
    assert payload["audio_url"].startswith("/artifacts/")
    assert set(payload["timings"]) == {
        "stt_ms",
        "llm_first_token_ms",
        "llm_total_ms",
        "tts_first_audio_ms",
        "tts_total_ms",
        "total_ms",
    }
    audio = client.get(payload["audio_url"])
    assert audio.status_code == 200
    validate_wav_bytes(audio.content)


def test_voice_turn_stream_returns_wav(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    wav = open("tests/fixtures/sample.wav", "rb").read()
    response = client.post(
        "/v1/voice-turn",
        files={"file": ("sample.wav", wav, "audio/wav")},
        data={"stream": "true"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    validate_wav_bytes(response.content)
