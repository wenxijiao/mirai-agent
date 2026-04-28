"""Optional speech-to-text providers for Mirai."""

from mirai.core.stt.base import SpeechToTextProvider, SttError, SttNotConfiguredError
from mirai.core.stt.factory import create_stt_provider, transcribe_audio
from mirai.core.stt.types import WHISPER_MULTILINGUAL_MODELS, TranscriptionResult
from mirai.core.stt.whisper_provider import ensure_whisper_weights_cached

__all__ = [
    "SpeechToTextProvider",
    "SttError",
    "SttNotConfiguredError",
    "TranscriptionResult",
    "WHISPER_MULTILINGUAL_MODELS",
    "create_stt_provider",
    "transcribe_audio",
    "ensure_whisper_weights_cached",
]
