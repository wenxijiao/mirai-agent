"""Incremental parse of ``<think>`` / ``<thinking>`` blocks in model streams."""

import re

# Common "reasoning" wrappers from various chat-tuned models (streaming-safe incremental parse).
_THINK_OPEN = re.compile(r"<(?:redacted_thinking|thinking|think)\b[^>]*>", re.IGNORECASE)
_THINK_CLOSE = re.compile(r"</(?:redacted_thinking|thinking|think)\b[^>]*>", re.IGNORECASE)


class ThinkTagParser:
    """Incremental parser that separates model reasoning tags from user-visible text."""

    def __init__(self):
        self._in_think = False
        self._buf = ""

    def feed(self, text: str):
        """Yield ``("thought", content)`` or ``("text", content)`` tuples."""
        self._buf += text
        while self._buf:
            if self._in_think:
                m = _THINK_CLOSE.search(self._buf)
                if m:
                    thought = self._buf[: m.start()]
                    self._buf = self._buf[m.end() :]
                    self._in_think = False
                    if thought:
                        yield ("thought", thought)
                else:
                    yield ("thought", self._buf)
                    self._buf = ""
            else:
                m = _THINK_OPEN.search(self._buf)
                if m:
                    before = self._buf[: m.start()]
                    self._buf = self._buf[m.end() :]
                    self._in_think = True
                    if before:
                        yield ("text", before)
                else:
                    yield ("text", self._buf)
                    self._buf = ""
