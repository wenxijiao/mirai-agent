"""Pydantic model for ~/.mirai/config.json."""

from typing import Any

from pydantic import BaseModel, Field, model_validator


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
    # IANA timezone (e.g. Pacific/Auckland) for user-facing wall clock: chat [Current Time],
    # proactive message context, proactive quiet hours, proactive daily send limit calendar.
    # Unset or null: those features use UTC for date windows; chat time fallback uses the host OS zone (see docs).
    # Legacy config key ``proactive_quiet_hours_timezone`` is still accepted on load.
    local_timezone: str | None = None
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
    # Proactive messaging (optional, default off): scheduled user-facing follow-ups.
    proactive_enabled: bool = False
    proactive_channels: list[str] = Field(default_factory=lambda: ["telegram"])
    proactive_session_ids: list[str] = Field(default_factory=list)
    proactive_daily_limit: int = Field(default=4, ge=0, le=100)
    proactive_quiet_hours: str = "00:30-08:30"
    proactive_check_interval_seconds: int = Field(default=900, ge=60, le=86400)
    proactive_min_idle_minutes: int = Field(default=45, ge=1, le=10080)
    proactive_unreplied_escalation_minutes: int = Field(default=180, ge=1, le=10080)
    proactive_profile: str = "default"
    proactive_profile_prompt: str | None = None
    proactive_tone_intensity: str = "gentle"
    # Jitter check loop sleep: sample in [base*(1-ratio), base*(1+ratio)] clamped to [60, 86400].
    proactive_check_interval_jitter_ratio: float = Field(default=0.15, ge=0.0, le=0.5)
    # Stable random scale for unreplied follow-up threshold (0 = exact escalation minutes).
    proactive_unreplied_escalation_jitter_ratio: float = Field(default=0.0, ge=0.0, le=0.5)
    # Probability each eligible check emits a proactive check-in (when not in unreplied escalation path).
    proactive_check_in_probability: float = Field(default=0.35, ge=0.0, le=1.0)
    # Speech-to-text (optional): disabled by default so text-only installs stay lightweight.
    stt_provider: str = "disabled"
    stt_backend: str = "faster-whisper"
    stt_model: str | None = None
    stt_model_dir: str | None = None
    stt_language: str = "auto"

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_local_timezone(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        lt = data.get("local_timezone")
        legacy = data.get("proactive_quiet_hours_timezone")
        legacy_empty = legacy is None or (isinstance(legacy, str) and not legacy.strip())
        lt_empty = lt is None or (isinstance(lt, str) and not str(lt).strip())
        if lt_empty and not legacy_empty and isinstance(legacy, str):
            merged = {**data}
            merged["local_timezone"] = legacy.strip()
            return merged
        return data


RECOMMENDED_CHAT_MODEL = "qwen3.5:9b"
RECOMMENDED_EMBEDDING_MODEL = "qwen3-embedding:0.6b"
RECOMMENDED_STT_MODEL = "base"
