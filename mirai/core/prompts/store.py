"""Persisted system / per-session prompts (backed by ~/.mirai/config.json via ModelConfig)."""

from mirai.core.config.store import load_model_config, load_saved_model_config, save_model_config
from mirai.core.prompts.defaults import DEFAULT_SYSTEM_PROMPT


def get_system_prompt() -> str:
    config = load_model_config()
    prompt = config.system_prompt.strip() if config.system_prompt else ""
    return prompt or DEFAULT_SYSTEM_PROMPT


def set_system_prompt(system_prompt: str) -> str:
    normalized = system_prompt.strip()
    if not normalized:
        raise ValueError("System prompt cannot be empty.")

    config = load_saved_model_config()
    config.system_prompt = normalized
    save_model_config(config)
    return normalized


def reset_system_prompt() -> str:
    config = load_saved_model_config()
    config.system_prompt = None
    save_model_config(config)
    return DEFAULT_SYSTEM_PROMPT


def get_session_prompt(session_id: str) -> str | None:
    """Return a per-session system prompt, or None to use the global default."""
    return load_saved_model_config().session_prompts.get(session_id)


def set_session_prompt(session_id: str, prompt: str) -> str:
    config = load_saved_model_config()
    config.session_prompts[session_id] = prompt.strip()
    save_model_config(config)
    return config.session_prompts[session_id]


def delete_session_prompt(session_id: str) -> None:
    config = load_saved_model_config()
    config.session_prompts.pop(session_id, None)
    save_model_config(config)


def get_effective_system_prompt(session_id: str) -> str:
    """Resolved system text for a session: per-session override or global default."""
    session_prompt = get_session_prompt(session_id)
    if session_prompt:
        return session_prompt
    return get_system_prompt()
