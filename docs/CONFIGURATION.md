# Configuration

Mirai's main persistent settings live in one file: `~/.mirai/config.json`.

To create or refresh that file with every known key and its default value:

```bash
mirai --config
```

Edit that JSON file for normal persistent configuration. Environment variables are still supported and always override the file at runtime, which is useful for secrets, Docker, CI, and system services.

## Config File Reference

`config.json` is standard JSON, so it cannot contain comments. Run `mirai --config` whenever you want a complete file with every currently supported key.

Model and provider fields:

- `chat_provider`: Chat model provider. Common values: `ollama`, `openai`, `gemini`, `claude`. Default: `ollama`.
- `chat_model`: Chat model name. `null` means Mirai will use provider defaults/setup.
- `embedding_provider`: Embedding provider. Default: `ollama`.
- `embedding_model`: Embedding model name. `null` means provider default/setup.
- `embedding_dim`: Optional embedding vector dimension override. Usually leave `null`.
- `openai_api_key`, `openai_base_url`, `gemini_api_key`, `claude_api_key`: Saved provider credentials/base URL. Environment variables override these.

Prompt and session fields:

- `system_prompt`: Global system prompt override. `null` uses Mirai's default prompt.
- `session_prompts`: Per-session prompt overrides, keyed by session id such as `tg_123`.
- `chat_append_current_time`: Append current time to normal chat system context. Default: `true`.
- `chat_append_tool_use_instruction`: Append Mirai tool-use guidance when tools are available. Default: `true`.

Connection and UI fields:

- `connection_code`: Saved LAN/relay/WebSocket connection code for clients and Edge SDKs.
- `ui_dark_mode`: UI dark mode preference. Default: `true`.
- `lan_secret`: Local LAN pairing secret. Usually managed by Mirai.

Memory fields:

- `memory_max_recent_messages`: Recent same-session messages included in context. Default: `10`.
- `memory_max_related_messages`: Related cross-session memory snippets included in context. `0` disables cross-session related memory. Default: `5`.

Tool policy fields:

- `local_tools_always_allow`: Server-local tool names that do not require confirmation.
- `local_tools_force_confirm`: Server-local tool names that always require confirmation.
- `edge_tools_enable_dynamic_routing`: Rank and cap Edge tools per turn. Default: `true`.
- `edge_tools_retrieval_limit`: Max Edge tool schemas exposed per turn. Default: `20`.
- `core_tools_always_include`: Keep core server tools loaded when enabled. Default: `true`.
- `core_tools_allow_disable`: Allow core tools to be disabled by tool policy/UI. Default: `true`.

Telegram fields:

- `telegram_bot_token`: Telegram Bot API token from BotFather. Environment variable: `TELEGRAM_BOT_TOKEN`.
- `telegram_allowed_user_ids`: Optional numeric Telegram user allowlist. Empty means no allowlist.

LINE fields:

- `line_channel_secret`: LINE Messaging API channel secret.
- `line_channel_access_token`: LINE channel access token.
- `line_bot_port`: Port for the LINE webhook sidecar. Default: `8788`.
- `line_allowed_user_ids`: Optional LINE user allowlist. Empty means no allowlist.

Proactive messaging fields:

- `proactive_enabled`: Enable proactive outbound messages. Default: `false`.
- `proactive_channels`: Channels to use. First version supports `telegram`. Default: `["telegram"]`.
- `proactive_session_ids`: Target sessions, for example `["tg_123456"]`. Empty means no target.
- `proactive_daily_limit`: Max proactive sends per session per day. Default: `4`.
- `proactive_quiet_hours`: Quiet-hour window, such as `00:30-08:30`. Default: `00:30-08:30`.
- `proactive_check_interval_seconds`: Background check interval. Default: `900`.
- `proactive_min_idle_minutes`: Minimum idle time after user/proactive activity before a check-in. Default: `45`.
- `proactive_unreplied_escalation_minutes`: Time before an unreplied follow-up can escalate. Default: `180`.
- `proactive_profile`: Open profile label. Built-in hints include `default`, `companion`, `tutor`, and `coach`, but custom labels are allowed.
- `proactive_profile_prompt`: Custom proactive style instructions. When set, this has priority over built-in profile hints.
- `proactive_tone_intensity`: Follow-up intensity. Suggested values: `gentle`, `medium`, `strong`. Default: `gentle`.

Speech-to-text fields:

- `stt_provider`: Speech-to-text provider. `disabled` by default; `whisper` enables local Whisper.
- `stt_backend`: STT backend. Default: `faster-whisper`.
- `stt_model`: Whisper model name, for example `base`, `small`, or `turbo`.
- `stt_model_dir`: Optional model cache directory. `null` uses Mirai's default.
- `stt_language`: Language hint. Default: `auto`.

## Environment Variables

### Model & API Keys

| Variable | Description |
|---|---|
| `MIRAI_CHAT_PROVIDER` | Override chat provider (`ollama`, `openai`, `gemini`, `claude`) |
| `MIRAI_CHAT_MODEL` | Override chat model |
| `MIRAI_EMBEDDING_PROVIDER` | Override embedding provider |
| `MIRAI_EMBED_MODEL` | Override embedding model |
| `OPENAI_API_KEY` | OpenAI-compatible API key |
| `OPENAI_BASE_URL` | Custom OpenAI-compatible base URL |
| `GEMINI_API_KEY` | Gemini API key |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key |
| `OLLAMA_HOST` | Ollama server URL (default `http://127.0.0.1:11434`; useful when Ollama runs on a different host or in Docker) |

### Server & Connection

| Variable | Description |
|---|---|
| `MIRAI_SERVER_URL` | Manual direct server URL (default `http://127.0.0.1:8000`) |
| `MIRAI_CONNECTION_CODE` | Connection code for edge SDKs (LAN code or WebSocket URL) |
| `MIRAI_USER_ACCESS_TOKEN` | Bearer token for clients when talking to a multi-tenant `mirai-enterprise` server (ignored by OSS) |

### Memory

| Variable | Description |
|---|---|
| `MIRAI_MEMORY_MAX_RECENT` | Max recent messages included in context (integer) |
| `MIRAI_MEMORY_MAX_RELATED` | Max semantically related memories included in context (integer) |

### Chat Behaviour

| Variable | Description |
|---|---|
| `MIRAI_CHAT_APPEND_CURRENT_TIME` | Set to `1`/`true` to append the current time to the system prompt |
| `MIRAI_CHAT_APPEND_TOOL_INSTRUCTION` | Set to `1`/`true` to append tool-use instructions to the system prompt |

### Proactive Messaging

| Variable | Description |
|---|---|
| `MIRAI_PROACTIVE_ENABLED` | Enable proactive outbound messages (default `false`) |
| `MIRAI_PROACTIVE_CHANNELS` | Comma-separated channels, currently `telegram` |
| `MIRAI_PROACTIVE_SESSION_IDS` | Comma-separated target sessions, for example `tg_123456` |
| `MIRAI_PROACTIVE_DAILY_LIMIT` | Max proactive sends per session per day (default `4`) |
| `MIRAI_PROACTIVE_QUIET_HOURS` | Local quiet-hour window like `00:30-08:30` |
| `MIRAI_PROACTIVE_CHECK_INTERVAL_SECONDS` | Background check interval (default `900`) |
| `MIRAI_PROACTIVE_MIN_IDLE_MINUTES` | Minimum idle time after user/proactive activity before a check-in (default `45`) |
| `MIRAI_PROACTIVE_UNREPLIED_ESCALATION_MINUTES` | Time before an unreplied follow-up can escalate (default `180`) |
| `MIRAI_PROACTIVE_PROFILE` | Open profile label, for example `default`, `companion`, `tutor`, `coach`, or custom |
| `MIRAI_PROACTIVE_PROFILE_PROMPT` | Custom proactive behavior prompt, overrides preset guidance |
| `MIRAI_PROACTIVE_TONE_INTENSITY` | `gentle`, `medium`, or `strong` |

For a more frequent companion-style setup, prefer editing the same keys in `~/.mirai/config.json` after running `mirai --config`.

### Speech-to-Text

| Variable | Description |
|---|---|
| `MIRAI_STT_PROVIDER` | STT provider (`disabled` or `whisper`; default `disabled`) |
| `MIRAI_STT_BACKEND` | Whisper backend (`faster-whisper`; default) |
| `MIRAI_STT_MODEL` | Multilingual Whisper model (`tiny`, `base`, `small`, `medium`, `large`, or `turbo`) |
| `MIRAI_STT_MODEL_DIR` | Model cache directory (default `~/.mirai/models/whisper`) |
| `MIRAI_STT_LANGUAGE` | STT language hint (default `auto`) |
| `HF_TOKEN` or `HUGGING_FACE_HUB_TOKEN` | Optional Hugging Face Hub token for higher rate limits when downloading Whisper weights (same env vars Hugging Face tools expect). |

Put `HF_TOKEN=hf_...` in **`~/.mirai/.env`** or **`./.env`** if you want; Mirai loads those files early via `python-dotenv` (without overwriting variables already set in your shell).

Speech-to-text is optional and disabled by default. Run `mirai --setup` to enable local multilingual Whisper for Telegram voice/audio, LINE audio, audio uploads in the web UI, or `/transcribe <path>` in `mirai --chat`.

The **faster-whisper** Python package is included in the default `mirai-agent` install. **Model weight files** are large and are not in the git repository; when you pick an STT model in `mirai --setup`, Mirai **downloads the weights to** `~/.mirai/models/whisper` (or your chosen directory) so the first real voice message is not stuck waiting on the network.

The setup wizard exposes only multilingual Whisper models: `tiny`, `base`, `small`, `medium`, `large`, and `turbo`. `base` is the recommended starter choice; `tiny` is lighter, while `small` and above trade more disk/CPU/GPU resources for better accuracy.

### Tool Routing

| Variable | Description |
|---|---|
| `MIRAI_EDGE_TOOLS_DYNAMIC_ROUTING` | Set to `1`/`true` to rank and cap Edge tools per chat turn (default `true`) |
| `MIRAI_EDGE_TOOLS_RETRIEVAL_LIMIT` | Number of Edge tool schemas exposed per chat turn, `0`-`200` (default `20`) |

Core Mirai tools are always loaded when enabled. Edge tools are registered in full, but when dynamic routing is enabled Mirai embeds the current request and Edge tool retrieval documents, then exposes only the most relevant Edge tools to the model. If embeddings are unavailable, Mirai falls back to deterministic lexical matching.

You can also update the saved config from the terminal:

```bash
mirai --tool-routing
mirai --tool-routing --edge-tools-limit 30
mirai --tool-routing --disable-edge-tool-routing
mirai --tool-routing --enable-edge-tool-routing --edge-tools-limit 20
```

### Logging

| Variable | Description |
|---|---|
| `MIRAI_LOG_LEVEL` | Python logging level for server/UI (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`; default `WARNING`) |
| `MIRAI_HTTP_LOG` | Set to `1`/`true` to log every `httpx`/`httpcore` request at INFO (noisy; default is to silence them so Mirai log lines stay visible) |

### CORS & Security

| Variable | Description |
|---|---|
| `MIRAI_CORS_ORIGINS` | Comma-separated browser origins allowed to call the core API. Default: localhost origins only |
| `MIRAI_CORS_ALLOW_CREDENTIALS` | Set to `1`/`true` to allow browser credentials on the core API |
| `MIRAI_RELAY_CORS_ORIGINS` | Comma-separated browser origins allowed to call the Relay API. Default: localhost origins only |
| `MIRAI_RELAY_CORS_ALLOW_CREDENTIALS` | Set to `1`/`true` to allow browser credentials on Relay |

### Edge SDK

| Variable | Description |
|---|---|
| `EDGE_NAME` | Override edge device display name (defaults to system hostname) |
| `MIRAI_TOOL_CONFIRMATION_PATH` | Custom path for the tool confirmation policy file |

### Telegram

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) (optional Telegram bridge) |
| `TELEGRAM_ALLOWED_USER_IDS` | Comma-separated Telegram user IDs allowed to use the bot; empty = no restriction |

## Telegram

Telegram-related dependencies (`python-telegram-bot`, `httpx`) are included in the default install; no optional extras are required.

### Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Configure the token (any one of the following):
   - Set environment variable `TELEGRAM_BOT_TOKEN`
   - Add `"telegram_bot_token": "..."` to `~/.mirai/config.json`
   - Run `mirai --server --telegram` or `mirai --telegram` without a token set -- Mirai will prompt you to paste it and saves it to `~/.mirai/config.json`
3. Optionally restrict access: set `TELEGRAM_ALLOWED_USER_IDS` or add `"telegram_allowed_user_ids"` in config.
4. To accept voice/audio messages, enable STT in `mirai --setup` (Whisper weights are downloaded during setup when you select a model).

### Running

- **`mirai --server --telegram`** (recommended) -- starts the API and the Telegram bot together on one machine.
- **`mirai --telegram`** -- runs only the Telegram bot, connecting to the API like `mirai --chat` (LAN code / relay profile).

### Timer & Push Notifications

When a timer fires for a Telegram session (`tg_<user_id>`), the **API process** calls Telegram `sendMessage` directly. For this to work, the bot token must be available on the machine running `mirai --server`.

> If you run `mirai --telegram` on your laptop but `mirai --server` on a remote host, you must also configure the same bot token on the remote host (via env or config file), or use `mirai --server --telegram` on a single machine.

### Troubleshooting

- **Restart** the API after changing the token if it was already running.
- If messages fail, check server logs -- Telegram often returns HTTP 200 with `ok: false` (e.g. user blocked the bot, wrong chat_id). Run with `MIRAI_LOG_LEVEL=DEBUG` for details.
- **Delayed actions** ("in 1 minute do X") only work if the model actually calls the `set_timer` / `schedule_task` tool. Plain text promises do nothing. Check with `MIRAI_LOG_LEVEL=INFO` -- you should see `Tool call: set_timer session_id=...` in the logs. If not, try rephrasing or using a model with stronger tool-use support.

## Data Storage

| Path | Contents |
|---|---|
| `~/.mirai/config.json` | Model config, prompt config, saved connection code |
| `~/.mirai/profiles.json` | Saved remote profiles |
| `~/.mirai/memory/` | Session history and embeddings |

`config.json` can hold **multiple provider API keys at once** (`openai_api_key`, `gemini_api_key`, `claude_api_key`, and optional `openai_base_url`). Environment variables still win when set. `mirai --setup` only asks for what the chosen chat/embedding providers need; you can add other keys later via the web UI **Model Configuration** dialog or by editing `config.json`, so switching providers does not require re-entering keys once they are saved.

To clear only memory and embeddings (keeping config and profiles):

```bash
mirai --cleanup-memory
```

To delete all Mirai user data (`~/.mirai/`):

```bash
mirai --cleanup
```

## Connection Codes

When `mirai --server` starts, it prints:

- A permanent LAN code
- A temporary 24-hour LAN code

You can use those codes from `--chat`, `--ui`, `--edge`, or from any SDK.

Mirai saves the last successful connection code in `~/.mirai/config.json` and reuses it automatically.

## Remote Access

For personal remote access, the recommended path is Tailscale.

Typical flow:

1. Install Tailscale on the server and the remote device
2. Put both on the same Tailnet
3. Run `mirai --server` on the host machine
4. Use the Tailscale hostname or IP from `mirai --ui` or `mirai --chat`

Mirai also supports a relay-based pairing flow, but it is optional and not the default setup.

## Deployment Hardening

Mirai defaults to **local-first** operation. Browser CORS is limited to localhost-style origins by default, and browser credentials are disabled unless you explicitly opt in.

- Keep the core API on `127.0.0.1` unless you intentionally trust your LAN.
- Prefer Tailscale or another private network over exposing the core API directly.
- If you expose Relay behind HTTPS for browser clients, set exact origins with `MIRAI_RELAY_CORS_ORIGINS`.
- If you need third-party browser pages to call the core API, set `MIRAI_CORS_ORIGINS` explicitly instead of relying on permissive wildcards.

## Docker

Build and run the API server (data persisted in a Docker volume for `/root/.mirai`):

```bash
docker compose up --build
```

To pass model configuration, uncomment or add environment variables in `docker-compose.yml`:

```yaml
environment:
  MIRAI_CHAT_PROVIDER: openai
  MIRAI_CHAT_MODEL: gpt-4o
  OPENAI_API_KEY: sk-...
```

See [`docker-compose.yml`](../docker-compose.yml) and [`Dockerfile`](../Dockerfile). You still need a reachable LLM (for example Ollama on the host); set `OLLAMA_HOST` or model env vars as appropriate.
