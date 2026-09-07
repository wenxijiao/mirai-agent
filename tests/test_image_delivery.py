"""Images must reach a vision model and remain private when reopened from history."""

import asyncio
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from yumi.core.chatbot import YumiBot
from yumi.core.features.config.model import ModelConfig
from yumi.core.features.prompts import composer
from yumi.core.features.uploads import service
from yumi.core.features.uploads.router import router
from yumi.core.platform.http.dependencies import current_identity_dependency
from yumi.core.platform.plugins import Identity
from yumi.core.platform.runtime.assistant_context import PromptSnapshot
from yumi.core.platform.runtime.caller_context import reset_chat_owner_user_id, set_chat_owner_user_id


@pytest.fixture
def image_path(tmp_path, monkeypatch):
    root = tmp_path / ".yumi" / "uploads"
    path = root / "alice" / "s" / "photo.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"private image bytes")
    monkeypatch.setattr(service, "uploads_root", lambda: root)
    monkeypatch.setattr(composer, "_get_uploads_root", lambda: root)
    return path


def test_authenticated_image_download_and_owner_boundaries(image_path):
    app = FastAPI()
    app.include_router(router)
    identity = Identity("alice")
    app.dependency_overrides[current_identity_dependency] = lambda: identity
    with TestClient(app) as client:
        response = client.get("/uploads/content", params={"path": str(image_path)})
        assert response.status_code == 200
        assert response.content == image_path.read_bytes()
        assert response.headers["cache-control"] == "private, no-store"
        identity = Identity("bob")
        assert client.get("/uploads/content", params={"path": str(image_path)}).status_code == 404
        link = image_path.parents[2] / "bob" / "alias.png"
        link.parent.mkdir()
        link.symlink_to(image_path)
        assert client.get("/uploads/content", params={"path": str(link)}).status_code == 404
        assert client.get("/uploads/content", params={"path": "/etc/passwd"}).status_code == 404

        def unauthenticated():
            raise HTTPException(401)

        app.dependency_overrides[current_identity_dependency] = unauthenticated
        assert client.get("/uploads/content", params={"path": str(image_path)}).status_code == 401


def test_prompt_inlining_is_owner_scoped(image_path):
    messages = [{"role": "user", "content": f"What is this? {image_path}"}]
    for owner, expected in [("alice", True), ("bob", False)]:
        token = set_chat_owner_user_id(owner)
        try:
            result = composer._inline_uploaded_images(messages)
            assert composer.messages_have_multimodal_images(result) is expected
            assert messages[0]["content"].startswith("What is this?")
        finally:
            reset_chat_owner_user_id(token)


def test_vision_model_follows_snapshot_across_loop_and_leaves_text_model_unchanged(image_path, monkeypatch):
    captured = []

    class Provider:
        async def chat_stream(self, **kwargs):
            captured.append(kwargs)
            yield {"type": "finish", "reason": "stop"}

    memory = Mock()
    memory.session_id = "s"
    memory.get_context.side_effect = lambda **k: [{"role": "system", "content": "Help the user."}]
    bot = YumiBot(Provider(), "text-model", runtime_config=ModelConfig(chat_vision_model="vision-model"))
    monkeypatch.setattr(bot, "_get_memory", lambda _: memory)
    monkeypatch.setattr("yumi.core.chatbot.turn_inspector.record_llm_request", lambda *a, **k: None)
    snapshot = PromptSnapshot()

    async def run():
        token = set_chat_owner_user_id("alice")
        try:
            for prompt, snap in [(str(image_path), snapshot), (None, snapshot), ("hello", PromptSnapshot())]:
                async for _ in bot.chat_stream(prompt=prompt, prompt_snapshot=snap):
                    pass
        finally:
            reset_chat_owner_user_id(token)

    asyncio.run(run())
    assert [c["model"] for c in captured] == ["vision-model", "vision-model", "text-model"]
    assert all(composer.messages_have_multimodal_images(c["messages"]) for c in captured[:2])
    assert bot.model_name == "text-model"


def test_configured_vision_rejection_does_not_silently_remove_image(image_path, monkeypatch):
    calls = []

    class Provider:
        async def chat_stream(self, **kwargs):
            calls.append(kwargs)
            raise ValueError("model does not support vision")
            yield  # pragma: no cover

    memory = Mock()
    memory.session_id = "s"
    memory.get_context.return_value = []
    bot = YumiBot(Provider(), "text-model", runtime_config=ModelConfig(chat_vision_model="vision-model"))
    monkeypatch.setattr(bot, "_get_memory", lambda _: memory)
    monkeypatch.setattr("yumi.core.chatbot.turn_inspector.record_llm_request", lambda *a, **k: None)
    monkeypatch.setattr("yumi.core.chatbot.write_provider_failure_diagnostic", lambda **k: None)

    async def run():
        token = set_chat_owner_user_id("alice")
        try:
            with pytest.raises(ValueError, match="vision"):
                async for _ in bot.chat_stream(prompt=str(image_path)):
                    pass
        finally:
            reset_chat_owner_user_id(token)

    asyncio.run(run())
    assert len(calls) == 1
    memory.delete_message.assert_called_once()
