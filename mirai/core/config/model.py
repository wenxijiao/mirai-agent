"""Pydantic model for ~/.mirai/config.json."""

from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    chat_provider: str = "ollama"
    chat_model: str | None = None
    embedding_provider: str = "ollama"
    embedding_model: str | None = None
    embedding_dim: int | None = None
    system_prompt: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    gemini_api_key: str | None = None
    claude_api_key: str | None = None
    connection_code: str | None = None
    session_prompts: dict[str, str] = {}
    ui_dark_mode: bool = True
    lan_secret: str | None = None
    # Server-local tools only (names in TOOL_REGISTRY, not edge_*__*).
    local_tools_always_allow: list[str] = Field(default_factory=list)
    local_tools_force_confirm: list[str] = Field(default_factory=list)
    # Chat context: last N messages in the current session (user + assistant rows).
    memory_max_recent_messages: int = Field(default=10, ge=1, le=500)
    # Cross-session RAG snippets injected as a system block (0 = off).
    memory_max_related_messages: int = Field(default=5, ge=0, le=100)
    # Appended to the system message each chat request (can disable to save tokens / avoid English policy text).
    chat_append_current_time: bool = True
    chat_append_tool_use_instruction: bool = True
    # Tool routing: core server tools stay loaded; edge tools are ranked and capped per turn.
    edge_tools_enable_dynamic_routing: bool = True
    edge_tools_retrieval_limit: int = Field(default=20, ge=0, le=200)
    core_tools_always_include: bool = True
    core_tools_allow_disable: bool = True
    # Telegram bot (optional): token in config or TELEGRAM_BOT_TOKEN; empty allowed_user_ids = no restriction
    telegram_bot_token: str | None = None
    telegram_allowed_user_ids: list[int] = Field(default_factory=list)
    # LINE Messaging API (optional): secrets in config or LINE_* env; empty line_allowed_user_ids = no restriction
    line_channel_secret: str | None = None
    line_channel_access_token: str | None = None
    line_bot_port: int = Field(default=8788, ge=1, le=65535)
    line_allowed_user_ids: list[str] = Field(default_factory=list)


RECOMMENDED_CHAT_MODEL = "qwen3.5:9b"
RECOMMENDED_EMBEDDING_MODEL = "qwen3-embedding:0.6b"
