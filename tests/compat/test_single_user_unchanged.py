"""Regression: default single-user mode stays usable without Bearer tokens."""

import mirai.core.api.routes as routes_mod
from fastapi.testclient import TestClient
from mirai.core.api.routes import app


def test_chat_post_works_without_bearer_single_user_mode(monkeypatch):
    async def fake_gen(prompt: str, session_id: str, think: bool = False):
        yield {"type": "text", "content": "x"}

    monkeypatch.setattr(routes_mod, "generate_chat_events", fake_gen)

    client = TestClient(app)
    r = client.post("/chat", json={"prompt": "hi", "session_id": "default"})
    assert r.status_code == 200


def test_health_single_user_identity():
    client = TestClient(app)
    d = client.get("/health").json()
    assert d["status"] == "ok"
    assert d["identity_user_id"] == "_local"
