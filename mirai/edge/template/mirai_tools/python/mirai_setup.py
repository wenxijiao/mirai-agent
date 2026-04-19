"""
Mirai Edge — Python tool registration

Import your own functions and register them with a description.
Parameter types are auto-extracted from type hints, and parameter
descriptions from the docstring Args section.

Usage — embed in your app::

    from mirai_tools.python.mirai_setup import init_mirai

    init_mirai()
    # Your program continues to run as usual

Quick test — run this file only (no separate main.py)::

    python -m mirai_tools.python.mirai_setup

    # or from ``mirai_tools/python/``:
    python mirai_setup.py

Requires: pip install websockets

Multi-tenant server (``mirai-enterprise``): set ``MIRAI_ACCESS_TOKEN`` to your user
``mirai_...`` token if your deployment requires authenticated Edge registration.
"""

try:
    from .mirai_sdk import MiraiAgent
except ImportError:
    # ``python mirai_setup.py`` from ``mirai_tools/python/`` (not as a package)
    from mirai_sdk import MiraiAgent

# ── Import your tool functions ──
# from my_app.actions import jump, run


def init_mirai():
    agent = MiraiAgent(
        # connection_code="mirai-lan_...",  # or set MIRAI_CONNECTION_CODE in .env
        # edge_name="My Device",              # or set EDGE_NAME in .env
    )

    # ── Register tools: func + description ──
    # The description tells the AI when and how to use the tool.
    # Tool name and parameter types are auto-extracted from the function.
    #
    # agent.register(jump, "Make the character jump")
    # agent.register(run, "Make the character run at a given speed")
    #
    # Dangerous tools: user confirms in the Mirai web UI or `mirai --chat` (not on device):
    # agent.register(delete_all, "Delete all data", require_confirmation=True)
    #
    # Tool confirmation choices (Tools page / chat "always allow") are saved next to your
    # .env as .mirai_tool_confirmation.json (override with MIRAI_TOOL_CONFIRMATION_PATH).

    agent.run_in_background()
    return agent


if __name__ == "__main__":
    import sys
    import threading

    init_mirai()
    print("Mirai edge running (setup as __main__). Press Ctrl+C to stop.", file=sys.stderr)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
