"""Shared pytest configuration for OSS tests (single-user)."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_mirai_env(monkeypatch):
    """Strip enterprise-only env vars so tests run cleanly against OSS defaults."""
    for var in (
        "MIRAI_TENANCY_MODE",
        "MIRAI_DB_URL",
        "MIRAI_RELAY_URL",
        "MIRAI_ACCESS_TOKEN",
        "MIRAI_USER_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)
