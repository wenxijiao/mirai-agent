# Configuration

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
