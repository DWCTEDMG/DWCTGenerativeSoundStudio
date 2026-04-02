from __future__ import annotations

from functools import lru_cache
from typing import Any


@lru_cache(maxsize=4)
def _load_model(model_size: str):
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception as e:
        raise RuntimeError("ASR requires optional deps: pip install -e '.[asr]'") from e
    return WhisperModel(model_size, device="cpu", compute_type="int8")


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def transcribe_detailed(path: str, model_size: str = "small") -> dict[str, Any]:
    """Transcribe audio with long-form metadata and timestamped segments."""
    model = _load_model(str(model_size or "small"))
    segments_iter, info = model.transcribe(
        path,
        beam_size=1,
        best_of=1,
        temperature=0.0,
        condition_on_previous_text=False,
        without_timestamps=False,
        vad_filter=True,
        no_speech_threshold=0.7,
    )
    raw_segments = list(segments_iter)
    duration_after_vad = _coerce_float(getattr(info, "duration_after_vad", 0.0) or 0.0)
    if not raw_segments or duration_after_vad <= 0.0:
        return {
            "text": "",
            "segments": [],
            "language": str(getattr(info, "language", "") or ""),
            "duration_s": _coerce_float(getattr(info, "duration", 0.0) or 0.0),
            "duration_after_vad_s": duration_after_vad,
            "segment_count": 0,
            "word_count": 0,
            "model_size": str(model_size or "small"),
            "source": "faster_whisper",
        }

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
    return {
        "text": text,
        "segments": segments,
        "language": str(getattr(info, "language", "") or ""),
        "duration_s": _coerce_float(getattr(info, "duration", 0.0) or 0.0),
        "duration_after_vad_s": duration_after_vad,
        "segment_count": len(segments),
        "word_count": len(text.split()),
        "model_size": str(model_size or "small"),
        "source": "faster_whisper",
    }


def transcribe(path: str, model_size: str = "small") -> str:
    """Transcribe audio to text using optional faster-whisper (CPU-friendly).

    Install:
      pip install -e ".[asr]"
    """
    return str(transcribe_detailed(path, model_size=model_size).get("text") or "")
