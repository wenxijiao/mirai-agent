"""In-core LINE webhook (OSS single-user): signature + empty events + happy text."""

import base64
import hashlib
import hmac
import json

import mirai.core.api.routes as api
from fastapi.testclient import TestClient
from mirai.line.client import LineMessagingClient


def _sign(body: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(mac).decode("ascii")


def test_line_webhook_bad_signature(monkeypatch):
    monkeypatch.setenv("MIRAI_LINE_INCORE", "1")
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "sec")
    body = b'{"events":[]}'
    with TestClient(api.app) as client:
        r = client.post("/line/webhook", content=body, headers={"X-Line-Signature": "bad"})
    assert r.status_code == 401


def test_line_webhook_ok_empty_events(monkeypatch):
    monkeypatch.setenv("MIRAI_LINE_INCORE", "1")
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "sec")
    body = b'{"events":[]}'
    sig = _sign(body, "sec")
    with TestClient(api.app) as client:
        r = client.post("/line/webhook", content=body, headers={"X-Line-Signature": sig})
    assert r.status_code == 200


async def _noop_coro(*_a, **_k):
    return None


async def _stream_one_text(*_a, **_k):
    yield {"type": "text", "content": "ok"}


def test_line_webhook_text_message_single_user(monkeypatch):
    """Signed text event in single-user mode → 200 (chat stream mocked)."""
    monkeypatch.setenv("MIRAI_LINE_INCORE", "1")
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "sec")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")

    monkeypatch.setattr("mirai.line.handlers.stream_line_chat", _stream_one_text)
    monkeypatch.setattr(LineMessagingClient, "reply_message", _noop_coro)
    monkeypatch.setattr(LineMessagingClient, "push_message", _noop_coro)

    payload = {
        "events": [
            {
                "type": "message",
                "replyToken": "dummy-reply-token",
                "source": {"type": "user", "userId": "Uoss1"},
                "message": {"type": "text", "id": "mid1", "text": "hello"},
            }
        ]
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = _sign(body, "sec")
    with TestClient(api.app) as client:
        r = client.post("/line/webhook", content=body, headers={"X-Line-Signature": sig})
    assert r.status_code == 200
