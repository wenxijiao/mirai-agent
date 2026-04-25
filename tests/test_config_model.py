"""Default model config values (no network, no server)."""

from mirai.core.config import ModelConfig


def test_model_config_default_provider():
    cfg = ModelConfig()
    assert cfg.chat_provider == "ollama"
    assert cfg.embedding_provider == "ollama"
    assert cfg.chat_append_current_time is True
    assert cfg.chat_append_tool_use_instruction is True
    assert cfg.edge_tools_enable_dynamic_routing is True
    assert cfg.edge_tools_retrieval_limit == 20
