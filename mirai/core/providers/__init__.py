from __future__ import annotations

from mirai.core.providers.base import BaseLLMProvider

SUPPORTED_PROVIDERS = ("ollama", "openai", "gemini", "claude")


def create_provider(
    provider_name: str,
    *,
    credentials: dict[str, str | None] | None = None,
) -> BaseLLMProvider:
    """Instantiate a provider by name.

    Credentials default to env var > ~/.mirai/config.json; pass *credentials* to override.
    """
    from mirai.core.config import get_api_credentials

    creds = credentials if credentials is not None else get_api_credentials()

    if provider_name == "ollama":
        from mirai.core.providers.ollama_provider import OllamaProvider

        return OllamaProvider()

    if provider_name == "openai":
        from mirai.core.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=creds["openai_api_key"],
            base_url=creds["openai_base_url"],
        )

    if provider_name == "gemini":
        from mirai.core.providers.gemini_provider import GeminiProvider

        return GeminiProvider(api_key=creds["gemini_api_key"])

    if provider_name == "claude":
        from mirai.core.providers.claude_provider import ClaudeProvider

        return ClaudeProvider(api_key=creds["claude_api_key"])

    raise ValueError(f"Unknown provider: '{provider_name}'. Supported providers: {', '.join(SUPPORTED_PROVIDERS)}")


__all__ = ["BaseLLMProvider", "create_provider", "SUPPORTED_PROVIDERS"]
