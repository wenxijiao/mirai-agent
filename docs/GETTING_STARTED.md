# Getting Started

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com/) if you use the default local provider
- API keys for cloud providers such as OpenAI or Gemini

## Install

If you are installing from PyPI:

```bash
pip install mirai-agent
```

If you are installing from source:

```bash
git clone https://github.com/wenxijiao/Mirai.git
cd Mirai
pip install .
```

For development:

```bash
pip install -e ".[dev]"
```

### PyPI and npm

| Artifact | Install |
|----------|---------|
| **Python app & server** | PyPI package name: **`mirai-agent`** (publish when ready). Until then: `pip install .` from a clone. |
| **TypeScript SDK** | npm package name: **`mirai-sdk`** ([`mirai/sdk/typescript/package.json`](../mirai/sdk/typescript/package.json)). Until published: copy from this repo or use `mirai --edge`. |
| **Go, Swift, Java, C++, Rust, Kotlin, Dart, UE5** | Vendored from [`mirai/sdk/`](../mirai/sdk/README.md) or copied into your project via `mirai --edge`; not published as language-specific registry packages yet. |

Publishing tagged releases to PyPI and npm is documented in [CONTRIBUTING.md](../CONTRIBUTING.md#releases-pypi--npm).

### CI

Every push and pull request to `main` runs GitHub Actions: Python (`pytest`, `ruff`, `compileall`), TypeScript / C++ / Go / Swift / Java SDK builds, and other jobs defined in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

## First Run

1. Start the server:

```bash
mirai --server
```

Keep this running in its own terminal. Open a second terminal for `mirai --chat`, `mirai --ui`, or `mirai --demo`.

2. On first run, Mirai guides you through:
   - Chat provider selection
   - Chat model selection
   - Embedding provider selection
   - Embedding model selection
   - Required API keys

3. To rerun setup later:

```bash
mirai --setup
```

## Providers

| Provider | Chat | Embedding | Notes |
|---|---|---|---|
| `ollama` | Yes | Yes | Local models, no API key needed |
| `openai` | Yes | Yes | Also works with OpenAI-compatible endpoints |
| `gemini` | Yes | Yes | Google Gemini |
| `claude` | Yes | No | Anthropic Claude (use another provider for embeddings) |

You can mix providers — for example OpenAI for chat and Ollama for embeddings.

## Web UI

```bash
mirai --ui
```

The UI includes:

- **Chat**: session management, search, pinning, streaming replies
- **Tools**: server tools and connected edge devices
- **Settings**: models, prompts, appearance, runtime config

## Terminal Chat

```bash
mirai --chat
```

Useful commands:

| Command | Description |
|---|---|
| `/help` | Show commands |
| `/prompt` | Inspect prompt state |
| `/prompt set <text>` | Set session prompt |
| `/prompt default` | Reset session prompt |
| `/prompt global` | Show global prompt |
| `/prompt global set <text>` | Update global prompt |
| `/prompt global reset` | Reset built-in global prompt |
| `/model` | Show current model config |
| `/session` | Show current session ID |
| `/clear` | Clear current session |

## Demo

Mirai ships with a dual-window demo suite that demonstrates one agent controlling
two independent Python applications at once.

```bash
mirai --server
mirai --demo
```

Keep `mirai --server` running in its own terminal, then launch `mirai --demo` from a second terminal.

The demo requires a graphical desktop session. On Linux, install Tk support first (for example `sudo apt install python3-tk` on Debian/Ubuntu).

This opens:

- `Smart Home` (`mirai.demo.smart_home`) — house devices and rooms (card grid)
- `Planner` (`mirai.demo.planner`) — tkinter schedule app: mini calendar + day timeline; tools `add_event`, `remove_event`, `update_event`, `get_schedule`, `clear_schedule`, `set_reminder`

Then open `mirai --chat` or `mirai --ui` and ask the agent to control both.

The demo windows are display-only (no in-GUI buttons). Both windows show the same status format (`Connected · EdgeName · Tools`) so users can quickly understand that one session controls two apps.

Try these one-line prompts:

- `Turn on the kitchen lights and add a "Cook dinner" event at 18:00 for 1 hour, category personal.`
- `Set thermostat to 22, and show me today's schedule.`
- `Lock the front door, add "Team standup" tomorrow at 10:00 for 30 minutes, category meeting.`
- `Turn off bedroom lamp, remove the "Lunch with Alex" event.`
- `Open garden gate, update "Code review" to start at 15:00 instead.`
- `Brew coffee, set a reminder for "Morning run" 15 minutes before.`

## Automated Tests

```bash
pip install -e ".[dev]"
pytest
```

See [TESTING.md](TESTING.md) for more details.

## Cleanup

```bash
mirai --cleanup
```

This removes `~/.mirai/`. Ollama and its model files are not touched.

To clear only saved chat memory and embeddings while keeping config and profiles:

```bash
mirai --cleanup-memory
```

This removes `~/.mirai/memory/` (and any legacy memory directory) but keeps model settings, prompts, and saved connection info.
