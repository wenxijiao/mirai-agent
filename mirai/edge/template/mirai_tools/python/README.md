# Mirai Edge — Python

Use this when your app is written in Python and you want the LLM to call functions inside the same process.

## Quick Start

1. Install the only runtime dependency:

```bash
pip install websockets
```

2. Edit `mirai_tools/python/mirai_setup.py`
3. Set your connection in `mirai_tools/.env` or pass it directly to `MiraiAgent(...)`
4. Either call `init_mirai()` from your app, **or** run the setup file alone for a quick test (no `main.py`):

```bash
# from your project root (where `mirai_tools/` lives)
python -m mirai_tools.python.mirai_setup
```

```bash
# or from mirai_tools/python/
python mirai_setup.py
```

The file includes `if __name__ == "__main__":` so it blocks until Ctrl+C (the edge client runs in a background thread).

## Files In This Folder

```text
mirai_tools/python/
├── README.md
├── __init__.py
├── mirai_setup.py          # edit this
└── mirai_sdk/
    ├── __init__.py
    └── agent_client.py     # bundled SDK, usually leave as-is
```

## Configure Connection

Recommended `.env` file:

```env
MIRAI_CONNECTION_CODE=mirai-lan_...
EDGE_NAME=My Device
```

You can also pass values directly in `mirai_setup.py`.

## Register Tools

Open `mirai_setup.py` and register your functions:

```python
from .mirai_sdk import MiraiAgent
from my_app.actions import jump


def init_mirai():
    agent = MiraiAgent()
    agent.register(jump, "Make the character jump")
    agent.run_in_background()
    return agent
```

Python is the most automatic SDK:

- tool name comes from `func.__name__`
- parameter types come from type hints
- parameter descriptions can come from the docstring `Args:` section

Use `require_confirmation=True` for dangerous actions.

## Start It From Your App

```python
from mirai_tools.python.mirai_setup import init_mirai

agent = init_mirai()
```

Your own program keeps running as usual.

## Notes

- The SDK looks for `mirai_tools/.env` first, then `./.env`
- Tool confirmation choices are stored next to the `.env` file as `.mirai_tool_confirmation.json`
- If your entry script runs from a different working directory, either `cd` to the project root first or pass `connection_code` / `edge_name` directly
