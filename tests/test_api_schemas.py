"""Pydantic API schema validation."""

from mirai.core.api.schemas import ChatRequest, ModelConfigUpdateRequest


def test_chat_request_defaults():
    r = ChatRequest(prompt="hi")
    assert r.session_id == "default"
    assert r.think is False


def test_model_config_update_optional_fields():
    r = ModelConfigUpdateRequest()
    assert r.chat_provider is None
    assert r.memory_max_recent_messages is None
