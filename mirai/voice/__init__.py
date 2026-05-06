"""Microphone voice session for ``mirai --server --voice``.

Submodules:

* :mod:`mirai.voice.audio_source` – pluggable mic capture (real / fake).
* :mod:`mirai.voice.wake` – wake-word detection (Picovoice Porcupine).
* :mod:`mirai.voice.segmenter` – VAD-based utterance collection.
* :mod:`mirai.voice.runtime` – the asyncio loop wiring everything together.
* :mod:`mirai.voice.dispatch` – send transcribed prompts into ``generate_chat_events``.

Optional dependency: ``pip install mirai-agent[voice,stt]``.
"""
