import pytest


@pytest.mark.unit
def test_port_default():
    from app.config import Settings

    s = Settings(_env_file=None)
    assert s.port == 8080


@pytest.mark.unit
def test_port_env_override(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("PORT", "9090")
    s = Settings(_env_file=None)
    assert s.port == 9090
