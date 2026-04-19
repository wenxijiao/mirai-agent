"""CORS configuration helpers for core and Relay apps."""

from mirai.core.http_config import DEFAULT_LOCAL_BROWSER_ORIGINS, get_cors_settings


def test_cors_defaults_are_localhost_only(monkeypatch):
    monkeypatch.delenv("TEST_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("TEST_CORS_ALLOW_CREDENTIALS", raising=False)

    settings = get_cors_settings("TEST_CORS_ORIGINS", "TEST_CORS_ALLOW_CREDENTIALS")

    assert settings["allow_origins"] == list(DEFAULT_LOCAL_BROWSER_ORIGINS)
    assert settings["allow_credentials"] is False


def test_cors_wildcard_forces_credentials_off(monkeypatch):
    monkeypatch.setenv("TEST_CORS_ORIGINS", "*")
    monkeypatch.setenv("TEST_CORS_ALLOW_CREDENTIALS", "true")

    settings = get_cors_settings("TEST_CORS_ORIGINS", "TEST_CORS_ALLOW_CREDENTIALS")

    assert settings["allow_origins"] == ["*"]
    assert settings["allow_credentials"] is False


def test_cors_allows_explicit_origin_list(monkeypatch):
    monkeypatch.setenv("TEST_CORS_ORIGINS", "https://app.example, https://admin.example")
    monkeypatch.setenv("TEST_CORS_ALLOW_CREDENTIALS", "1")

    settings = get_cors_settings("TEST_CORS_ORIGINS", "TEST_CORS_ALLOW_CREDENTIALS")

    assert settings["allow_origins"] == ["https://app.example", "https://admin.example"]
    assert settings["allow_credentials"] is True
