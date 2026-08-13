from __future__ import annotations

import gc
import weakref

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


def test_cuda_failure_retries_same_model_on_cpu_before_model_fallback(monkeypatch):
    calls: list[tuple[str, bool, str, str]] = []
    release_calls: list[bool] = []

    def fake_transcribe_once(
        _path: str,
        model_size: str,
        *,
        vad_filter: bool,
        device: str,
        compute_type: str,
    ) -> dict[str, object]:
        calls.append((model_size, vad_filter, device, compute_type))
        if device == "cuda":
            raise RuntimeError("secret CUDA loader detail: cublas64_12.dll")
        return {
            "text": "CPU fallback transcript",
            "segments": [{"text": "CPU fallback transcript"}],
            "duration_s": 1.0,
            "duration_after_vad_s": 1.0,
            "model_size": model_size,
            "device": device,
            "compute_type": compute_type,
        }

    monkeypatch.setattr(asr, "_transcribe_once", fake_transcribe_once)
    monkeypatch.setattr(asr, "_release_failed_cuda_whisper_models", lambda: release_calls.append(True))

    result = asr._transcribe_faster_whisper(
        "speech.wav",
        model_size="turbo",
        device="cuda",
        compute_type="float16",
    )

    assert calls == [
        ("turbo", True, "cuda", "float16"),
        ("turbo", True, "cpu", "int8"),
    ]
    assert release_calls == [True]
    assert result["model_size"] == "turbo"
    assert result["device"] == "cpu"
    assert result["compute_type"] == "int8"
    assert result["requested_device"] == "cuda"
    assert result["device_fallback_used"] is True
    assert result["device_fallback_note"] == asr.CUDA_ASR_CPU_FALLBACK_NOTE
    assert "note" not in result
    assert "cublas64_12.dll" not in str(result)


def test_no_vad_retry_uses_the_successful_cpu_fallback_profile(monkeypatch):
    calls: list[tuple[bool, str, str]] = []

    def fake_transcribe_once(
        _path: str,
        model_size: str,
        *,
        vad_filter: bool,
        device: str,
        compute_type: str,
    ) -> dict[str, object]:
        assert model_size == "turbo"
        calls.append((vad_filter, device, compute_type))
        if device == "cuda":
            raise RuntimeError("CUDA inference unavailable")
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
    monkeypatch.setattr(asr, "_release_failed_cuda_whisper_models", lambda: None)

    result = asr._transcribe_faster_whisper(
        "music.wav",
        model_size="turbo",
        device="cuda",
        compute_type="float16",
    )

    assert calls == [
        (True, "cuda", "float16"),
        (True, "cpu", "int8"),
        (False, "cpu", "int8"),
    ]
    assert result["note"] == asr.NO_SPEECH_AFTER_VAD_NOTE
    assert result["device_fallback_note"] == asr.CUDA_ASR_CPU_FALLBACK_NOTE
    assert result["requested_device"] == "cuda"


def test_no_vad_cuda_failure_retries_same_model_on_cpu(monkeypatch):
    calls: list[tuple[bool, str, str]] = []
    release_calls: list[bool] = []

    def fake_transcribe_once(
        _path: str,
        model_size: str,
        *,
        vad_filter: bool,
        device: str,
        compute_type: str,
    ) -> dict[str, object]:
        assert model_size == "turbo"
        calls.append((vad_filter, device, compute_type))
        if not vad_filter and device == "cuda":
            raise RuntimeError("secret CUDA no-VAD inference detail")
        return {
            "text": "" if vad_filter else "CPU no-VAD transcript",
            "segments": [] if vad_filter else [{"text": "CPU no-VAD transcript"}],
            "duration_s": 8.0,
            "duration_after_vad_s": 0.0 if vad_filter else 8.0,
            "model_size": model_size,
            "device": device,
            "compute_type": compute_type,
        }

    monkeypatch.setattr(asr, "_transcribe_once", fake_transcribe_once)
    monkeypatch.setattr(asr, "_release_failed_cuda_whisper_models", lambda: release_calls.append(True))

    result = asr._transcribe_faster_whisper(
        "speech.wav",
        model_size="turbo",
        device="cuda",
        compute_type="float16",
    )

    assert calls == [
        (True, "cuda", "float16"),
        (False, "cuda", "float16"),
        (False, "cpu", "int8"),
    ]
    assert release_calls == [True]
    assert result["text"] == "CPU no-VAD transcript"
    assert result["device"] == "cpu"
    assert result["compute_type"] == "int8"
    assert result["requested_device"] == "cuda"
    assert "note" not in result
    assert "secret CUDA no-VAD inference detail" not in str(result)


def test_failed_cuda_frame_is_released_before_cpu_retry(monkeypatch):
    class Marker:
        pass

    marker_ref: weakref.ReferenceType[Marker] | None = None

    def fake_transcribe_once(
        _path: str,
        model_size: str,
        *,
        vad_filter: bool,
        device: str,
        compute_type: str,
    ) -> dict[str, object]:
        nonlocal marker_ref
        assert model_size == "turbo"
        assert vad_filter is True
        if device == "cuda":
            marker = Marker()
            marker_ref = weakref.ref(marker)
            raise RuntimeError("CUDA inference unavailable")

        gc.collect()
        assert marker_ref is not None
        assert marker_ref() is None
        return {
            "text": "CPU fallback transcript",
            "segments": [{"text": "CPU fallback transcript"}],
            "duration_s": 1.0,
            "duration_after_vad_s": 1.0,
            "model_size": model_size,
            "device": device,
            "compute_type": compute_type,
        }

    monkeypatch.setattr(asr, "_transcribe_once", fake_transcribe_once)
    monkeypatch.setattr(asr, "_release_failed_cuda_whisper_models", gc.collect)

    result = asr._transcribe_faster_whisper(
        "speech.wav",
        model_size="turbo",
        device="cuda",
        compute_type="float16",
    )

    assert result["text"] == "CPU fallback transcript"
