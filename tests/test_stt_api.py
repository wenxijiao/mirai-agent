"""STT API contract tests with the provider mocked out."""

from __future__ import annotations

import asyncio
import base64

import pytest
from fastapi import HTTPException
from mirai.core.api.routes import stt_transcribe_endpoint
from mirai.core.api.schemas import TranscribeRequest
from mirai.core.plugins import LOCAL_IDENTITY
from mirai.core.stt import SttNotConfiguredError, TranscriptionResult, ensure_whisper_weights_cached


def test_stt_transcribe_endpoint_uses_provider(monkeypatch):
    async def _fake_transcribe(audio: bytes, *, filename: str, language: str | None = None):
        assert audio == b"audio"
        assert filename == "voice.ogg"
        assert language is None
        return TranscriptionResult(text="hello", language="en", duration_seconds=1.2)

    monkeypatch.setattr("mirai.core.stt.transcribe_audio", _fake_transcribe)
    req = TranscribeRequest(filename="voice.ogg", content_base64=base64.b64encode(b"audio").decode("ascii"))

    response = asyncio.run(stt_transcribe_endpoint(LOCAL_IDENTITY, req))

    assert response["text"] == "hello"
    assert response["language"] == "en"
    assert response["duration_seconds"] == 1.2


def test_stt_transcribe_endpoint_reports_disabled(monkeypatch):
    async def _fake_transcribe(*_args, **_kwargs):
        raise SttNotConfiguredError("STT is not enabled")

    monkeypatch.setattr("mirai.core.stt.transcribe_audio", _fake_transcribe)
    req = TranscribeRequest(filename="voice.ogg", content_base64=base64.b64encode(b"audio").decode("ascii"))

    with pytest.raises(HTTPException) as ei:
        asyncio.run(stt_transcribe_endpoint(LOCAL_IDENTITY, req))

    assert ei.value.status_code == 400
    assert "STT is not enabled" in str(ei.value.detail)


@pytest.mark.parametrize(
    ("model", "repo_id", "fw_id"),
    [
        ("tiny", "Systran/faster-whisper-tiny", "tiny"),
        ("base", "Systran/faster-whisper-base", "base"),
        ("small", "Systran/faster-whisper-small", "small"),
        ("medium", "Systran/faster-whisper-medium", "medium"),
        ("large", "Systran/faster-whisper-large-v3", "large-v3"),
        ("turbo", "mobiuslabsgmbh/faster-whisper-large-v3-turbo", "large-v3-turbo"),
    ],
)
def test_ensure_whisper_weights_cached_triggers_model_download(monkeypatch, tmp_path, model, repo_id, fw_id):
    calls: list[tuple[str, dict]] = []
    snapshot_calls: list[tuple[tuple, dict]] = []

    def _fake_snapshot_download(*args, **kwargs):
        snapshot_calls.append((args, kwargs))
        return str(tmp_path / "hf-cache")

    class _FakeWhisperModel:
        def __init__(self, model_id: str, **kwargs: object) -> None:
            calls.append((model_id, kwargs))

    monkeypatch.setattr("huggingface_hub.snapshot_download", _fake_snapshot_download)
    monkeypatch.setattr("faster_whisper.WhisperModel", _FakeWhisperModel)
    ensure_whisper_weights_cached(model=model, model_dir=str(tmp_path))
    assert len(snapshot_calls) == 1
    assert snapshot_calls[0][0][0] == repo_id
    assert snapshot_calls[0][1]["cache_dir"] == str(tmp_path)
    assert snapshot_calls[0][1]["tqdm_class"] is not None
    assert len(calls) == 1
    assert calls[0][0] == fw_id
    assert calls[0][1]["device"] == "cpu"
    assert calls[0][1]["compute_type"] == "int8"
    assert str(tmp_path) in calls[0][1]["download_root"]
    assert calls[0][1]["local_files_only"] is True
