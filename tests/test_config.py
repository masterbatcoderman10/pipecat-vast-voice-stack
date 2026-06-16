import importlib


def test_settings_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("PORT", "7777")
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    config = importlib.import_module("app.config")
    settings = config.get_settings()
    assert settings.mock_mode is True
    assert settings.port == 7777
    assert settings.artifact_dir == tmp_path
    assert settings.stt_url.endswith(":9001")
