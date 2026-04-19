"""Planner (tkinter) demo — run with ``python -m mirai.demo.planner`` or ``mirai --demo``."""

from __future__ import annotations


def run_demo(connection_code: str | None = None) -> None:
    """Delegate to ``__main__`` so ``init_mirai`` lives only in the process entrypoint."""
    from mirai.demo.planner.__main__ import run_demo as _run_demo_entry

    _run_demo_entry(connection_code)


__all__ = ["run_demo"]
