"""Durable, account-owned invocation records and atomic execution claims."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone


class ToolRunStore:
    def __init__(self, sqlite, owner):
        self.sqlite, self.owner = sqlite, owner
        with sqlite.connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS tool_runs (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                owner TEXT NOT NULL, tool_name TEXT NOT NULL, request_key TEXT,
                status TEXT NOT NULL, record_json TEXT NOT NULL,
                UNIQUE(owner, request_key))""")
            conn.execute("CREATE INDEX IF NOT EXISTS tool_runs_owner_tool ON tool_runs(owner,tool_name,seq)")

    def create(self, record):
        timestamp = time.time()
        if record.get("created_at"):
            try:
                date = datetime.fromisoformat(record["created_at"])
                timestamp = (date if date.tzinfo else date.replace(tzinfo=timezone.utc)).timestamp()
            except (ValueError, TypeError):
                pass
        row = {"id": uuid.uuid4().hex, "created_at_num": int(timestamp * 1000), **record}
        with self.sqlite.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = (
                conn.execute(
                    "SELECT record_json FROM tool_runs WHERE owner=? AND request_key=?",
                    (self.owner, row.get("request_key")),
                ).fetchone()
                if row.get("request_key")
                else None
            )
            if existing:
                return json.loads(existing[0]), False
            inserted = conn.execute(
                "INSERT OR IGNORE INTO tool_runs(id,owner,tool_name,request_key,status,record_json) VALUES(?,?,?,?,?,?)",
                (row["id"], self.owner, row["tool_name"], row.get("request_key"), row["status"], json.dumps(row)),
            )
            if not inserted.rowcount:
                existing = conn.execute(
                    "SELECT record_json FROM tool_runs WHERE owner=? AND id=?", (self.owner, row["id"])
                ).fetchone()
                if not existing:
                    raise ValueError("Invocation id is already in use")
                return json.loads(existing[0]), False
        return row, True

    def get(self, run_id):
        with self.sqlite.connect() as conn:
            row = conn.execute(
                "SELECT record_json FROM tool_runs WHERE owner=? AND id=?", (self.owner, run_id)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def transition(self, run_id, expected, **changes):
        with self.sqlite.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            raw = conn.execute(
                "SELECT record_json FROM tool_runs WHERE owner=? AND id=?", (self.owner, run_id)
            ).fetchone()
            if not raw:
                return None, False
            row = json.loads(raw[0])
            if row["status"] not in expected:
                return row, False
            row.update(changes)
            conn.execute(
                "UPDATE tool_runs SET status=?,record_json=? WHERE owner=? AND id=?",
                (row["status"], json.dumps(row), self.owner, run_id),
            )
            return row, True

    def history(self, name, before=None, limit=50):
        with self.sqlite.connect() as conn:
            # Imported older calls must sort by invocation time, not import time.
            timestamp = "COALESCE(json_extract(record_json, '$.created_at_num'), 0)"
            cursor = (
                conn.execute(
                    f"SELECT {timestamp},seq FROM tool_runs WHERE owner=? AND tool_name=? AND seq=?",
                    (self.owner, name, before),
                ).fetchone()
                if before is not None
                else None
            )
            if before is not None and cursor is None:
                return {"runs": [], "next_before": None}
            rows = conn.execute(
                f"SELECT seq,record_json FROM tool_runs WHERE owner=? AND tool_name=? "
                f"AND ({timestamp},seq)<(?,?) ORDER BY {timestamp} DESC,seq DESC LIMIT ?",
                (
                    self.owner,
                    name,
                    *(tuple(cursor) if cursor else (9223372036854775807, 9223372036854775807)),
                    limit + 1,
                ),
            ).fetchall()
        return {
            "runs": [json.loads(r["record_json"]) for r in rows[:limit]],
            "next_before": rows[limit - 1]["seq"] if len(rows) > limit else None,
        }

    def import_chat_history(self, name, scope):
        """Import older durable chat calls once; newer calls arrive at trace time."""
        key = f"tool-history-import:{name}"
        from yumi.core.platform.storage.assistant_store import AssistantStore, is_group_session
        from yumi.core.platform.tools.trace import _truncate_args, _truncate_result_preview

        settings = AssistantStore(self.sqlite, self.owner)
        if settings.get(key):
            return
        with self.sqlite.connect() as conn:
            rows = conn.execute("SELECT detail_json FROM turn_traces ORDER BY started_at_num").fetchall()
        for raw in rows:
            trace = json.loads(raw[0])
            sid = trace.get("session_id", "")
            if is_group_session(sid) or scope.owner_user_from_session_id(sid) != self.owner:
                continue
            for step_index, step in enumerate(trace.get("rounds", [])):
                calls = {c.get("id"): c for c in step.get("tool_calls", []) if isinstance(c, dict)}
                for index, result in enumerate(step.get("tool_results", [])):
                    if (result.get("resolved_tool") or result.get("tool")) != name:
                        continue
                    call = calls.get(result.get("call_id"), {})
                    args = call.get("function", {}).get("arguments", {})
                    try:
                        args = json.loads(args) if isinstance(args, str) else args
                    except ValueError:
                        args = {}
                    # Historical traces did not record an exact approval decision.
                    self.create(
                        {
                            "id": (
                                f"ai-{trace['id']}-{result['call_id']}"
                                if result.get("call_id")
                                else f"legacy-{trace['id']}-{step_index}-{index}"
                            ),
                            "tool_name": name,
                            "origin": "ai",
                            "channel": trace.get("channel", "unknown"),
                            "session_id": sid,
                            "status": result.get("status", "success"),
                            "arguments": _truncate_args(args),
                            "result": _truncate_result_preview(result.get("result_preview", "")),
                            "duration_ms": result.get("duration_ms"),
                            "approval": "legacy",
                            "created_at": trace.get("started_at", ""),
                            "steps": [],
                        }
                    )
        settings.put(key, True)
