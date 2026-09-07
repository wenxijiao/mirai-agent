from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

from yumi.core.platform.providers.base import BaseLLMProvider, ProviderFinishReason, provider_finish_chunk
from yumi.core.platform.tools.normalize import normalize_tool_calls


def _normalize_openai_finish_reason(reason: Any) -> ProviderFinishReason:
    raw = str(getattr(reason, "value", reason) or "").strip().lower()
    if not raw or raw == "stop":
        return "stop"
    if raw == "length":
        return "length"
    if raw in {"content_filter", "safety", "blocked"}:
        return "blocked"
    # ``tool_calls`` without a usable collected call is an abnormal/unknown
    # terminal state. Valid tool calls take the explicit branch below.
    return "unknown"


def _normalize_messages_for_strict_openai_compat(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Preserve call identities and JSON-encode arguments at the wire boundary."""
    from yumi.core.platform.tools.replay import normalize_tool_history

    out = []
    for message in normalize_tool_history(messages):
        if message.get("tool_calls"):
            calls = []
            for call in message["tool_calls"]:
                function = dict(call.get("function") or {})
                args = function.get("arguments")
                function["arguments"] = (
                    json.dumps(args, ensure_ascii=False) if isinstance(args, (dict, list)) else (args or "")
                )
                calls.append({**call, "type": "function", "function": function})
            message = {**message, "tool_calls": calls}
        out.append(message)
    return out


def _strip_historical_reasoning(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop ``reasoning_content`` from assistant turns before the last user message.

    DeepSeek's thinking models require the chain-of-thought to be replayed
    inside the CURRENT turn's tool loop (assistant tool-call spans after the
    latest user prompt), but replaying CoT from completed historical turns is
    unnecessary — and expensive: each old turn's reasoning can be thousands of
    tokens, re-billed on every request while it stays in the recent-message
    window. Returns a shallow copy; input is left alone.
    """
    last_user = -1
    for i, msg in enumerate(messages):
        if msg.get("role") == "user":
            last_user = i
    if last_user == -1:
        return messages
    out: list[dict[str, Any]] = []
    for i, msg in enumerate(messages):
        if i < last_user and msg.get("role") == "assistant" and "reasoning_content" in msg:
            msg = {k: v for k, v in msg.items() if k != "reasoning_content"}
        out.append(msg)
    return out


def _convert_tool_schemas(tools: list[dict] | None) -> list[dict] | None:
    """Ensure tool schemas match the OpenAI format.

    Yumi internal schemas already use the OpenAI shape, so this is
    mostly a pass-through.  We strip any extra keys the API would reject.
    """
    if not tools:
        return None
    converted = []
    for t in tools:
        fn = t.get("function", {})
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {}),
                },
            }
        )
    return converted


class OpenAIProvider(BaseLLMProvider):
    """Provider for OpenAI and any OpenAI-compatible API.

    Covers: OpenAI, Azure OpenAI, vLLM, LM Studio, Groq, Together AI,
    DeepSeek, and any service that speaks the OpenAI chat completions
    protocol.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        api_family: str = "openai",
    ):
        try:
            from openai import AsyncOpenAI, OpenAI
        except ImportError as exc:
            raise ImportError(
                "The 'openai' package ships with yumi-agent but is missing here. "
                "Reinstall with: pip install --force-reinstall yumi-agent"
            ) from exc

        resolved_key = api_key or os.getenv("OPENAI_API_KEY") or ""
        resolved_url = base_url or os.getenv("OPENAI_BASE_URL") or None

        self.api_family = api_family
        self._sync_client = OpenAI(api_key=resolved_key, base_url=resolved_url)
        self._async_client = AsyncOpenAI(api_key=resolved_key, base_url=resolved_url)

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict] | None = None,
        think: bool = False,
    ) -> AsyncIterator[dict]:
        deepseek = getattr(self, "api_family", "openai") == "deepseek"
        replay = messages if deepseek and tools and think else _strip_historical_reasoning(messages)
        if deepseek and tools and think:
            # DeepSeek v4 requires the reasoning field on every replayed assistant
            # message with tools enabled, including completed previous turns.
            replay = [
                {**m, "reasoning_content": m.get("reasoning_content") or ""} if m.get("role") == "assistant" else m
                for m in replay
            ]
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": _normalize_messages_for_strict_openai_compat(replay),
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        converted_tools = _convert_tool_schemas(tools)
        if converted_tools:
            kwargs["tools"] = converted_tools

        if self.max_output_tokens:
            kwargs[
                "max_tokens"
                if deepseek or not model.startswith(("o1", "o3", "o4", "gpt-5"))
                else "max_completion_tokens"
            ] = self.max_output_tokens
        if deepseek:
            kwargs["extra_body"] = {"thinking": {"type": "enabled" if think else "disabled"}}
        yield {
            "type": "model_settings",
            "requested_think": think,
            "effective_think": think if deepseek else None,
            "thinking_control_supported": deepseek,
        }
        stream = await self._async_client.chat.completions.create(**kwargs)

        collected_tool_calls: dict[int, dict] = {}
        usage_payload = None
        finish_reason = None

        async for chunk in stream:
            u = getattr(chunk, "usage", None)
            if u is not None:
                usage_payload = u
            choice = chunk.choices[0] if chunk.choices else None
            if choice is not None and getattr(choice, "finish_reason", None) is not None:
                finish_reason = choice.finish_reason
            delta = choice.delta if choice is not None else None
            if delta is None:
                continue

            # DeepSeek (and a growing set of OpenAI-compatible providers) emits
            # chain-of-thought reasoning on a separate ``reasoning_content``
            # field next to ``content``. We surface it through the existing
            # ``thought`` chunk channel so downstream accumulation and UI
            # filtering keep working without a new event type.
            reasoning_delta = getattr(delta, "reasoning_content", None)
            if reasoning_delta:
                yield {"type": "thought", "content": reasoning_delta}

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    # Some OpenAI-compatible servers (older Azure deployments,
                    # some self-hosted vLLM builds) emit ``index = None``.
                    # Mixing ``int`` and ``None`` keys would crash the
                    # ``sorted(...)`` below, so backfill with the next slot.
                    idx = tc.index if tc.index is not None else len(collected_tool_calls)
                    if idx not in collected_tool_calls:
                        collected_tool_calls[idx] = {
                            "id": "",
                            "function": {"name": "", "arguments": ""},
                        }
                    entry = collected_tool_calls[idx]
                    # Capture the provider-issued tool_call id so the next
                    # turn's ``role: tool`` message can reference it (strict
                    # OpenAI-compatible servers like DeepSeek require this).
                    if getattr(tc, "id", None):
                        entry["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            entry["function"]["name"] += tc.function.name
                        if tc.function.arguments:
                            entry["function"]["arguments"] += tc.function.arguments

            content = delta.content
            if content:
                yield {"type": "text", "content": content}

        # Emit usage BEFORE tool_call. The chat consumers stop the stream on the
        # tool_call signal, so a usage chunk yielded after it would be dropped —
        # under-counting quota/cost on every tool-call turn.
        if usage_payload is not None:
            pt = int(getattr(usage_payload, "prompt_tokens", None) or 0)
            ct = int(getattr(usage_payload, "completion_tokens", None) or 0)
            # Cache-hit visibility: OpenAI reports prompt_tokens_details.cached_tokens,
            # DeepSeek reports prompt_cache_hit_tokens. Both are subsets of
            # prompt_tokens (billed at a discount), surfaced so traces can verify
            # the prefix actually caches.
            cached = 0
            details = getattr(usage_payload, "prompt_tokens_details", None)
            if details is not None:
                cached = int(getattr(details, "cached_tokens", None) or 0)
            if not cached:
                cached = int(getattr(usage_payload, "prompt_cache_hit_tokens", None) or 0)
            if pt or ct:
                payload: dict[str, Any] = {
                    "type": "usage",
                    "prompt_tokens": pt,
                    "completion_tokens": ct,
                    "model": model,
                }
                if cached:
                    payload["cached_prompt_tokens"] = cached
                yield payload

        if collected_tool_calls:
            tool_calls_list = []
            for idx in sorted(collected_tool_calls):
                tc = collected_tool_calls[idx]
                args_str = tc["function"]["arguments"]
                try:
                    tc["function"]["arguments"] = json.loads(args_str)
                except (json.JSONDecodeError, TypeError):
                    # Keep the raw string instead of swallowing to {}; normalize
                    # will try json-repair and, if even that fails, drop the call
                    # so the model regenerates (vs running with empty args).
                    tc["function"]["arguments"] = args_str
                tool_calls_list.append(tc)

            tool_calls_list = normalize_tool_calls(tool_calls_list)
            if tool_calls_list:
                yield {"type": "tool_call", "tool_calls": tool_calls_list}
                return

        yield provider_finish_chunk(
            _normalize_openai_finish_reason(finish_reason),
            provider_reason=finish_reason,
        )

    def embed(self, model: str, text: str) -> list[float]:
        response = self._sync_client.embeddings.create(model=model, input=text)
        from yumi.core.platform.runtime.usage_context import embedding_tokens

        embedding_tokens.set(getattr(getattr(response, "usage", None), "total_tokens", None))
        return list(response.data[0].embedding)

    def list_models(self) -> list[str]:
        try:
            models = self._sync_client.models.list()
            return [m.id for m in models.data]
        except Exception:
            return []

    async def shutdown(self, model: str) -> None:
        """Release the underlying httpx clients so connections / fds don't leak
        on lifespan teardown or PUT /config/model provider swaps."""
        client = getattr(self, "_async_client", None)
        if client is not None:
            try:
                await client.close()
            except Exception:
                pass
        sync_client = getattr(self, "_sync_client", None)
        if sync_client is not None:
            try:
                sync_client.close()
            except Exception:
                pass
