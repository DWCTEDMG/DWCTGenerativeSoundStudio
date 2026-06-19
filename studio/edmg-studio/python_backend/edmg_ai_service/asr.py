from __future__ import annotations

from functools import lru_cache
from typing import Any

NO_SPEECH_AFTER_VAD_NOTE = "No speech detected after VAD."
DEFAULT_MODEL_SIZE = "turbo"
DEFAULT_MODEL_FALLBACK_CHAIN = ("turbo", "large-v3", "medium", "small")
DEFAULT_ASR_PROVIDER = "faster_whisper"
DEFAULT_PARAKEET_MODEL = "nvidia/parakeet-tdt-0.6b-v3"


@lru_cache(maxsize=4)
def _load_model(model_size: str):
    return _load_faster_whisper_model(model_size, "cpu", "int8")


@lru_cache(maxsize=8)
def _load_faster_whisper_model(model_size: str, device: str, compute_type: str):
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception as e:
        raise RuntimeError("ASR requires optional deps: pip install -e '.[asr]'") from e
    return WhisperModel(model_size, device=device, compute_type=compute_type)


@lru_cache(maxsize=4)
def _load_parakeet_model(model_name: str, device: str):
    try:
        import nemo.collections.asr as nemo_asr  # type: ignore
    except Exception as e:
        raise RuntimeError(
            'Parakeet ASR requires optional deps: pip install -e ".[parakeet]"'
        ) from e

    model = nemo_asr.models.ASRModel.from_pretrained(model_name=model_name)
    if device == "cuda":
        try:
            model = model.to("cuda")
        except Exception as e:
            raise RuntimeError("Parakeet CUDA device requested but unavailable.") from e
    elif device == "cpu":
        try:
            model = model.to("cpu")
        except Exception:
            pass
    try:
        model.eval()
    except Exception:
        pass
    return model


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _fallback_model_candidates(model_size: str) -> list[str]:
    preferred = str(model_size or DEFAULT_MODEL_SIZE).strip().lower() or DEFAULT_MODEL_SIZE
    ordered: list[str] = []
    if preferred and preferred not in ordered:
        ordered.append(preferred)
    for candidate in DEFAULT_MODEL_FALLBACK_CHAIN:
        if candidate not in ordered:
            ordered.append(candidate)
    return ordered


def _normalize_provider(provider: str | None) -> str:
    raw = str(provider or DEFAULT_ASR_PROVIDER).strip().lower().replace("-", "_")
    if raw in {"whisper", "fasterwhisper", "faster_whisper"}:
        return "faster_whisper"
    if raw in {"parakeet", "nvidia_parakeet"}:
        return "parakeet"
    if raw in {"parakeet_nim", "nvidia_nim_asr", "nim_asr", "parakeet-nim"}:
        return "parakeet_nim"
    return DEFAULT_ASR_PROVIDER


def _normalize_whisper_device(device: str | None) -> str:
    raw = str(device or "cpu").strip().lower()
    if raw == "auto":
        try:
            import torch  # type: ignore

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"
    return raw if raw in {"cpu", "cuda"} else "cpu"


def _normalize_compute_type(compute_type: str | None, device: str) -> str:
    raw = str(compute_type or "int8").strip().lower()
    if raw == "auto":
        return "float16" if device == "cuda" else "int8"
    return raw if raw in {"float16", "int8", "int8_float16"} else "int8"


def _normalize_parakeet_model(model_size: str | None) -> str:
    raw = str(model_size or DEFAULT_PARAKEET_MODEL).strip()
    lower = raw.lower().replace("_", "-")
    if lower in {"v2", "parakeet-v2", "parakeet-tdt-0.6b-v2", "nvidia/parakeet-tdt-0.6b-v2"}:
        return "nvidia/parakeet-tdt-0.6b-v2"
    if lower in {"v3", "parakeet-v3", "parakeet-tdt-0.6b-v3", "nvidia/parakeet-tdt-0.6b-v3"}:
        return "nvidia/parakeet-tdt-0.6b-v3"
    return raw or DEFAULT_PARAKEET_MODEL


def _audio_duration_s(path: str) -> float:
    try:
        import soundfile as sf  # type: ignore

        info = sf.info(path)
        frames = _coerce_float(getattr(info, "frames", 0.0), 0.0)
        samplerate = _coerce_float(getattr(info, "samplerate", 0.0), 0.0)
        return frames / samplerate if frames > 0 and samplerate > 0 else 0.0
    except Exception:
        return 0.0


def _transcribe_once(
    path: str,
    model_size: str,
    *,
    vad_filter: bool,
    device: str = "cpu",
    compute_type: str = "int8",
) -> dict[str, Any]:
    if device == "cpu" and compute_type == "int8":
        model = _load_model(str(model_size or "small"))
    else:
        model = _load_faster_whisper_model(str(model_size or "small"), device, compute_type)
    segments_iter, info = model.transcribe(
        path,
        beam_size=1,
        best_of=1,
        temperature=0.0,
        condition_on_previous_text=False,
        without_timestamps=False,
        vad_filter=vad_filter,
        no_speech_threshold=0.7,
    )
    raw_segments = list(segments_iter)
    duration_s = _coerce_float(getattr(info, "duration", 0.0) or 0.0)
    duration_after_vad = _coerce_float(
        getattr(info, "duration_after_vad", duration_s if not vad_filter else 0.0)
        or (duration_s if not vad_filter else 0.0)
    )
    result = {
        "text": "",
        "segments": [],
        "language": str(getattr(info, "language", "") or ""),
        "duration_s": duration_s,
        "duration_after_vad_s": duration_after_vad,
        "segment_count": 0,
        "word_count": 0,
        "model_size": str(model_size or "small"),
        "source": "faster_whisper",
        "provider": "faster_whisper",
        "device": device,
        "compute_type": compute_type,
    }
    if not raw_segments or (vad_filter and duration_after_vad <= 0.0):
        return result

    lines: list[str] = []
    segments: list[dict[str, Any]] = []
    for seg in raw_segments:
        text = str(getattr(seg, "text", "") or "").strip()
        if not text:
            continue
        no_speech_prob = getattr(seg, "no_speech_prob", None)
        avg_logprob = getattr(seg, "avg_logprob", None)
        if isinstance(no_speech_prob, (int, float)) and float(no_speech_prob) >= 0.8 and len(text) < 24:
            continue
        if isinstance(avg_logprob, (int, float)) and float(avg_logprob) <= -1.2 and len(text) < 24:
            continue
        lines.append(text)
        segments.append(
            {
                "start": _coerce_float(getattr(seg, "start", 0.0) or 0.0),
                "end": _coerce_float(getattr(seg, "end", 0.0) or 0.0),
                "text": text,
                "avg_logprob": _coerce_float(avg_logprob, 0.0) if isinstance(avg_logprob, (int, float)) else None,
                "no_speech_prob": _coerce_float(no_speech_prob, 0.0) if isinstance(no_speech_prob, (int, float)) else None,
            }
        )

    text = "\n".join(lines).strip()
    result["text"] = text
    result["segments"] = segments
    result["segment_count"] = len(segments)
    result["word_count"] = len(text.split())
    return result


def _segment_from_parakeet_entry(entry: Any) -> dict[str, Any] | None:
    if isinstance(entry, dict):
        text = str(entry.get("text") or entry.get("segment") or entry.get("word") or "").strip()
        if not text:
            return None
        return {
            "start": _coerce_float(entry.get("start"), 0.0),
            "end": _coerce_float(entry.get("end"), 0.0),
            "text": text,
        }
    text = str(getattr(entry, "text", "") or getattr(entry, "segment", "") or "").strip()
    if not text:
        return None
    return {
        "start": _coerce_float(getattr(entry, "start", 0.0), 0.0),
        "end": _coerce_float(getattr(entry, "end", 0.0), 0.0),
        "text": text,
    }


def _extract_parakeet_result(raw: Any, path: str, model_name: str, device: str) -> dict[str, Any]:
    item = raw[0] if isinstance(raw, (list, tuple)) and raw else raw
    text = ""
    timestamp = None

    if isinstance(item, str):
        text = item.strip()
    elif isinstance(item, dict):
        text = str(item.get("text") or "").strip()
        timestamp = item.get("timestamp")
    else:
        text = str(getattr(item, "text", "") or "").strip()
        timestamp = getattr(item, "timestamp", None)

    segments: list[dict[str, Any]] = []
    if isinstance(timestamp, dict):
        raw_segments = timestamp.get("segment") or timestamp.get("segments") or []
        if isinstance(raw_segments, list):
            for entry in raw_segments:
                segment = _segment_from_parakeet_entry(entry)
                if segment:
                    segments.append(segment)

    duration_s = _audio_duration_s(path)
    if text and not segments:
        segments = [{"start": 0.0, "end": duration_s, "text": text}]

    if not text and segments:
        text = "\n".join(str(segment.get("text") or "").strip() for segment in segments).strip()

    return {
        "text": text,
        "segments": segments,
        "language": "",
        "duration_s": duration_s,
        "duration_after_vad_s": duration_s,
        "segment_count": len(segments),
        "word_count": len(text.split()),
        "model_size": model_name,
        "source": "nvidia_parakeet",
        "provider": "parakeet",
        "device": device,
        "compute_type": "nemo",
    }


def _transcribe_parakeet(path: str, model_size: str, *, device: str = "auto") -> dict[str, Any]:
    model_name = _normalize_parakeet_model(model_size)
    resolved_device = _normalize_whisper_device(device)
    model = _load_parakeet_model(model_name, resolved_device)
    try:
        raw = model.transcribe([path], timestamps=True)
    except TypeError:
        raw = model.transcribe([path])
    return _extract_parakeet_result(raw, path, model_name, resolved_device)


def _transcribe_faster_whisper(
    path: str,
    model_size: str = DEFAULT_MODEL_SIZE,
    *,
    device: str = "cpu",
    compute_type: str = "int8",
) -> dict[str, Any]:
    candidates = _fallback_model_candidates(model_size)
    last_error: Exception | None = None
    last_result: dict[str, Any] | None = None
    last_successful_model: str | None = None
    resolved_device = _normalize_whisper_device(device)
    resolved_compute_type = _normalize_compute_type(compute_type, resolved_device)

    for candidate in candidates:
        try:
            attempt = _transcribe_once(
                path,
                candidate,
                vad_filter=True,
                device=resolved_device,
                compute_type=resolved_compute_type,
            )
        except Exception as exc:
            last_error = exc
            continue
        last_result = attempt
        last_successful_model = candidate
        if attempt.get("text") or attempt.get("segments"):
            return attempt

    if last_successful_model is None:
        if last_error is not None:
            raise last_error
        raise RuntimeError("No Whisper models could be loaded for transcription.")

    if _coerce_float((last_result or {}).get("duration_after_vad_s"), 0.0) <= 0.0:
        without_vad = _transcribe_once(
            path,
            last_successful_model,
            vad_filter=False,
            device=resolved_device,
            compute_type=resolved_compute_type,
        )
        if without_vad.get("text") or without_vad.get("segments"):
            return without_vad
        without_vad["note"] = NO_SPEECH_AFTER_VAD_NOTE
        return without_vad

    return last_result or {
        "text": "",
        "segments": [],
        "language": "",
        "duration_s": 0.0,
        "duration_after_vad_s": 0.0,
        "segment_count": 0,
        "word_count": 0,
        "model_size": last_successful_model,
        "source": "faster_whisper",
        "provider": "faster_whisper",
        "device": resolved_device,
        "compute_type": resolved_compute_type,
    }


_NVIDIA_NIM_ASR_BASE = "https://ai.api.nvidia.com/v1/asr/nvidia"

# Map NIM model names to their catalog slugs
_NIM_MODEL_SLUG: dict[str, str] = {
    "parakeet-ctc-1.1b-asr": "parakeet-ctc-1_1b-asr",
    "parakeet-tdt-0.6b-v2":  "parakeet-tdt-0_6b-v2",
    "parakeet-ctc-0.6b-asr": "parakeet-ctc-0_6b-asr",
}


def _transcribe_parakeet_nim(
    path: str,
    model: str = "parakeet-ctc-1.1b-asr",
    *,
    api_key: str,
    language: str = "en-US",
    nim_base_url: str = "",
) -> dict[str, Any]:
    """Transcribe via NVIDIA NIM cloud ASR — no local GPU or NeMo needed.

    Uses the same NVIDIA API key as Nemotron / Cosmos (nvapi-...).
    Sends the audio file as multipart/form-data to the NIM speech endpoint.
    """
    import requests  # type: ignore

    slug = _NIM_MODEL_SLUG.get(model, model.replace(".", "_").replace("-", "_"))
    if nim_base_url:
        endpoint = nim_base_url.rstrip("/") + "/v1/audio/transcriptions"
    else:
        endpoint = f"{_NVIDIA_NIM_ASR_BASE}/{slug}/v1/audio/transcriptions"

    with open(path, "rb") as audio_file:
        resp = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (f"audio{_audio_ext(path)}", audio_file)},
            data={"language": language},
            timeout=(30, 300),
        )

    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail") or resp.text[:300]
        except Exception:
            detail = resp.text[:300]
        raise RuntimeError(
            f"NVIDIA NIM ASR returned {resp.status_code}: {detail}. "
            "Check your NVIDIA API key (same as Nemotron) in Settings."
        )

    data = resp.json()
    text = str(data.get("text") or "").strip()
    duration = _coerce_float(data.get("duration"))
    segments = []
    for seg in (data.get("segments") or []):
        segments.append({
            "start": _coerce_float(seg.get("start")),
            "end": _coerce_float(seg.get("end")),
            "text": str(seg.get("text") or "").strip(),
        })

    return {
        "text": text,
        "segments": segments,
        "duration": duration,
        "provider": "parakeet_nim",
        "model": model,
        "device": "cloud",
        "language": language,
    }


def _audio_ext(path: str) -> str:
    import os
    ext = os.path.splitext(path)[1].lower()
    return ext if ext in {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".webm"} else ".wav"


def transcribe_detailed(
    path: str,
    model_size: str = DEFAULT_MODEL_SIZE,
    *,
    provider: str = DEFAULT_ASR_PROVIDER,
    device: str = "cpu",
    compute_type: str = "int8",
    fallback_to_whisper: bool = True,
    nvidia_api_key: str = "",
    nim_base_url: str = "",
) -> dict[str, Any]:
    """Transcribe audio with long-form metadata and timestamped segments."""
    normalized_provider = _normalize_provider(provider)

    if normalized_provider == "parakeet_nim":
        try:
            return _transcribe_parakeet_nim(
                path,
                model=model_size or "parakeet-ctc-1.1b-asr",
                api_key=nvidia_api_key,
                nim_base_url=nim_base_url,
            )
        except Exception as exc:
            if not fallback_to_whisper:
                raise
            fallback = _transcribe_faster_whisper(path, DEFAULT_MODEL_SIZE, device="cpu", compute_type="int8")
            fallback["note"] = f"Parakeet NIM unavailable; used faster-whisper fallback: {exc}"
            fallback["requested_provider"] = "parakeet_nim"
            return fallback

    if normalized_provider == "parakeet":
        try:
            return _transcribe_parakeet(path, model_size, device=device)
        except Exception as exc:
            if not fallback_to_whisper:
                raise
            fallback = _transcribe_faster_whisper(
                path,
                DEFAULT_MODEL_SIZE,
                device="cpu",
                compute_type="int8",
            )
            fallback["note"] = f"Parakeet unavailable; used faster-whisper fallback: {exc}"
            fallback["requested_provider"] = "parakeet"
            fallback["requested_model_size"] = _normalize_parakeet_model(model_size)
            return fallback

    return _transcribe_faster_whisper(
        path,
        model_size=model_size,
        device=device,
        compute_type=compute_type,
    )


def transcribe(
    path: str,
    model_size: str = DEFAULT_MODEL_SIZE,
    *,
    provider: str = DEFAULT_ASR_PROVIDER,
    device: str = "cpu",
    compute_type: str = "int8",
    fallback_to_whisper: bool = True,
) -> str:
    """Transcribe audio to text using optional faster-whisper (CPU-friendly).

    Install:
      pip install -e ".[asr]"
    """
    return str(
        transcribe_detailed(
            path,
            model_size=model_size,
            provider=provider,
            device=device,
            compute_type=compute_type,
            fallback_to_whisper=fallback_to_whisper,
        ).get("text")
        or ""
    )
