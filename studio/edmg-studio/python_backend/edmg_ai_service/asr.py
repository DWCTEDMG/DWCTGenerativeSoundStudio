from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=4)
def _load_model(model_size: str):
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception as e:
        raise RuntimeError("ASR requires optional deps: pip install -e '.[asr]'") from e
    return WhisperModel(model_size, device="cpu", compute_type="int8")


def transcribe(path: str, model_size: str = "small") -> str:
    """Transcribe audio to text using optional faster-whisper (CPU-friendly).

    Install:
      pip install -e ".[asr]"
    """
    model = _load_model(str(model_size or "small"))
    segments_iter, info = model.transcribe(
        path,
        beam_size=1,
        best_of=1,
        temperature=0.0,
        condition_on_previous_text=False,
        without_timestamps=True,
        vad_filter=True,
        no_speech_threshold=0.7,
    )
    segments = list(segments_iter)
    if not segments:
        return ""
    if float(getattr(info, "duration_after_vad", 0.0) or 0.0) <= 0.0:
        return ""

    lines: list[str] = []
    for seg in segments:
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
    return "\n".join(lines).strip()
