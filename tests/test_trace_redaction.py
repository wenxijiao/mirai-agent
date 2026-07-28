"""Diagnostic endpoints must not hand one user's words to another.

Tool arguments read like telemetry but are not: `add_note(plan="明天记得买
牛奶")` is the user's own sentence. These endpoints exist to answer "is the
system healthy", so they get the shape of a call and not its contents — unless
the caller is looking at their own session, which is the whole of single-user
mode.
"""

from __future__ import annotations

import pytest
from yumi.core.platform.tools.trace import (
    redact_trace_content,
    redact_traces_for_viewer,
)


def _trace(session_id: str) -> dict:
    return {
        "id": "t-1",
        "session_id": session_id,
        "tool_name": "add_note",
        "status": "success",
        "duration_ms": 177,
        "arguments": {"title": "买牛奶", "plan": "明天记得买牛奶"},
        "result_preview": '{"ok": true, "id": "abc"}',
    }


@pytest.fixture
def two_user_scope(monkeypatch):
    """Sessions named `s:<owner>` so ownership is trivially resolvable."""
    import yumi.core.platform.plugins as plugins

    class _Scope:
        def owner_user_from_session_id(self, session_id: str) -> str:
            return session_id.split(":", 1)[1] if ":" in session_id else ""

    monkeypatch.setattr(plugins, "get_session_scope", lambda: _Scope())
    return _Scope()


def test_redact_keeps_shape_drops_words():
    out = redact_trace_content(_trace("s:u1"))
    assert "arguments" not in out
    assert "result_preview" not in out
    assert out["arguments_redacted"] is True
    assert out["result_redacted"] is True
    # The parts that describe the system, not the person, survive.
    assert out["tool_name"] == "add_note"
    assert out["duration_ms"] == 177
    assert out["status"] == "success"


def test_own_sessions_are_not_redacted(two_user_scope):
    [row] = redact_traces_for_viewer([_trace("s:u1")], "u1")
    assert row["arguments"] == {"title": "买牛奶", "plan": "明天记得买牛奶"}


def test_other_users_sessions_are_redacted(two_user_scope):
    [row] = redact_traces_for_viewer([_trace("s:u2")], "u1")
    assert "arguments" not in row
    assert "买牛奶" not in str(row)


def test_unresolvable_ownership_is_redacted(two_user_scope):
    """Fail closed: a session we cannot attribute is not assumed to be ours."""
    [row] = redact_traces_for_viewer([_trace("no-owner-marker")], "u1")
    assert "arguments" not in row


def test_scope_failure_is_redacted(monkeypatch):
    import yumi.core.platform.plugins as plugins

    class _Broken:
        def owner_user_from_session_id(self, session_id: str) -> str:
            raise RuntimeError("store down")

    monkeypatch.setattr(plugins, "get_session_scope", lambda: _Broken())
    [row] = redact_traces_for_viewer([_trace("s:u1")], "u1")
    assert "arguments" not in row
