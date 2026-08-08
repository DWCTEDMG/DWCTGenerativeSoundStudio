from __future__ import annotations

from edmg_ai_service import asr


def test_successful_empty_transcript_retries_same_model_without_vad(monkeypatch):
    calls: list[tuple[str, bool]] = []

    def fake_transcribe_once(
        _path: str,
        model_size: str,
        *,
        vad_filter: bool,
        device: str,
        compute_type: str,
    ) -> dict[str, object]:
        calls.append((model_size, vad_filter))
        return {
            "text": "",
            "segments": [],
            "duration_s": 8.0,
            "duration_after_vad_s": 0.0 if vad_filter else 8.0,
            "model_size": model_size,
            "device": device,
            "compute_type": compute_type,
        }

    monkeypatch.setattr(asr, "_transcribe_once", fake_transcribe_once)

    result = asr._transcribe_faster_whisper("music.wav", model_size="turbo")

    assert calls == [("turbo", True), ("turbo", False)]
    assert result["text"] == ""
    assert result["note"] == asr.NO_SPEECH_AFTER_VAD_NOTE


def test_model_fallback_is_reserved_for_load_or_inference_errors(monkeypatch):
    calls: list[str] = []

    def fake_transcribe_once(
        _path: str,
        model_size: str,
        *,
        vad_filter: bool,
        device: str,
        compute_type: str,
    ) -> dict[str, object]:
        calls.append(model_size)
        if model_size == "turbo":
            raise RuntimeError("preferred model is unavailable")
        return {
            "text": "fallback transcript",
            "segments": [{"text": "fallback transcript"}],
            "duration_s": 1.0,
            "duration_after_vad_s": 1.0,
            "model_size": model_size,
            "device": device,
            "compute_type": compute_type,
            "vad_filter": vad_filter,
        }

    monkeypatch.setattr(asr, "_transcribe_once", fake_transcribe_once)

    result = asr._transcribe_faster_whisper("speech.wav", model_size="turbo")

    assert calls == ["turbo", "large-v3"]
    assert result["text"] == "fallback transcript"
    assert result["model_size"] == "large-v3"
