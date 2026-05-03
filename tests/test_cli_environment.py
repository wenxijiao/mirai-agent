"""CLI environment selection tests without launching subprocesses."""

import json
import os
import sys

import mirai.cli as cli


def test_prepare_client_environment_prefers_reachable_direct_server(monkeypatch):
    monkeypatch.setenv("MIRAI_SERVER_URL", "http://127.0.0.1:8000")
    monkeypatch.delenv("MIRAI_RELAY_URL", raising=False)
    monkeypatch.delenv("MIRAI_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(cli, "is_server_running", lambda url: True)

    env = cli.prepare_client_environment("chat")

    assert env["MIRAI_SERVER_URL"] == "http://127.0.0.1:8000"


def test_reflex_ui_root_points_at_rxconfig():
    """Regression: UI lives under ``mirai/ui``, not ``mirai/cli/ui`` (see ``_reflex_ui_root``)."""
    root = cli._reflex_ui_root()
    assert os.path.isfile(os.path.join(root, "rxconfig.py"))


def test_main_dispatches_cleanup_memory(monkeypatch):
    called = {"memory": False}

    monkeypatch.setattr(sys, "argv", ["mirai", "--cleanup-memory"])
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli, "run_cleanup_memory", lambda: called.__setitem__("memory", True))

    cli.main()

    assert called["memory"] is True


def test_tool_routing_cli_updates_config(monkeypatch, tmp_path, capsys):
    p = tmp_path / "config.json"
    monkeypatch.setattr("mirai.core.config.paths.CONFIG_PATH", p)
    monkeypatch.setattr("mirai.core.config.store.CONFIG_PATH", p)
    monkeypatch.setattr(cli, "CONFIG_PATH", p)
    monkeypatch.setattr(
        sys, "argv", ["mirai", "--tool-routing", "--edge-tools-limit", "7", "--disable-edge-tool-routing"]
    )
    monkeypatch.setattr(cli, "configure_logging", lambda: None)

    cli.main()

    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["edge_tools_retrieval_limit"] == 7
    assert saved["edge_tools_enable_dynamic_routing"] is False
    out = capsys.readouterr().out
    assert "Edge dynamic routing: disabled" in out
    assert "Edge tools per turn:  7" in out


def test_config_cli_writes_full_config(monkeypatch, tmp_path, capsys):
    p = tmp_path / "config.json"
    monkeypatch.setattr("mirai.core.config.paths.CONFIG_PATH", p)
    monkeypatch.setattr("mirai.core.config.store.CONFIG_PATH", p)
    monkeypatch.setattr(cli, "CONFIG_PATH", p)
    monkeypatch.setattr(sys, "argv", ["mirai", "--config"])
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    opened = []
    monkeypatch.setattr(cli, "_open_path_with_default_app", lambda path: opened.append(path) or True)

    cli.main()

    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["proactive_enabled"] is False
    assert saved["proactive_quiet_hours"] == "00:30-08:30"
    assert opened == [p]
    out = capsys.readouterr().out
    assert "Mirai config written to:" in out
    assert "Opened config file" in out
    assert "Proactive messaging defaults:" in out
