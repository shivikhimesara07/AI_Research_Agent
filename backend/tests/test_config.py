from app.config import _secret


def test_secret_treats_empty_and_placeholder_as_unset(monkeypatch):
    for value in ["", "   ", "your-gemini-key-here", "YOUR-SEMANTIC-SCHOLAR-KEY-HERE"]:
        monkeypatch.setenv("SOME_API_KEY", value)
        assert _secret("SOME_API_KEY") is None


def test_secret_returns_real_value(monkeypatch):
    monkeypatch.setenv("SOME_API_KEY", " real-looking-key-123 ")
    assert _secret("SOME_API_KEY") == "real-looking-key-123"
    monkeypatch.delenv("SOME_API_KEY")
    assert _secret("SOME_API_KEY") is None
