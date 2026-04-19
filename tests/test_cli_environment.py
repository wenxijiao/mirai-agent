"""CLI environment selection tests without launching subprocesses."""

import sys

import mirai.cli as cli


def test_prepare_client_environment_prefers_reachable_direct_server(monkeypatch):
    monkeypatch.setenv("MIRAI_SERVER_URL", "http://127.0.0.1:8000")
    monkeypatch.delenv("MIRAI_RELAY_URL", raising=False)
    monkeypatch.delenv("MIRAI_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(cli, "is_server_running", lambda url: True)

    env = cli.prepare_client_environment("chat")

    assert env["MIRAI_SERVER_URL"] == "http://127.0.0.1:8000"


def test_main_dispatches_cleanup_memory(monkeypatch):
    called = {"memory": False}

    monkeypatch.setattr(sys, "argv", ["mirai", "--cleanup-memory"])
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli, "run_cleanup_memory", lambda: called.__setitem__("memory", True))

    cli.main()

    assert called["memory"] is True
