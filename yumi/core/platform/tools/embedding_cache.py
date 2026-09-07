"""Persistent vector cache for tool descriptions; never stores request text."""

from __future__ import annotations

import hashlib
import json
import sqlite3


def cache_key(provider, model: str, text: str) -> str:
    inner = getattr(provider, "_inner", provider)
    client = getattr(inner, "_sync_client", None)
    identity = f"{type(inner).__module__}.{type(inner).__name__}:{getattr(client, 'base_url', '')}"
    return hashlib.sha256(f"{identity}\0{model}\0{text}".encode()).hexdigest()


def _connect():
    from yumi.core.features.config.paths import CONFIG_DIR

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = CONFIG_DIR / "tool-vectors.sqlite3"
    conn = sqlite3.connect(path, timeout=5)
    path.chmod(0o600)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, value TEXT NOT NULL, touched INTEGER NOT NULL)"
    )
    return conn


def read_vector(key: str) -> list[float] | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT value FROM vectors WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()


def write_vector(key: str, vector: list[float]) -> None:
    conn = _connect()
    try:
        with conn:
            conn.execute("INSERT OR REPLACE INTO vectors VALUES (?, ?, unixepoch())", (key, json.dumps(vector)))
            conn.execute(
                "DELETE FROM vectors WHERE key IN (SELECT key FROM vectors ORDER BY touched DESC LIMIT -1 OFFSET 10000)"
            )
    finally:
        conn.close()
