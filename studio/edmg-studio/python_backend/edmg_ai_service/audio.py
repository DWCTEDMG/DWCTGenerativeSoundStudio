from __future__ import annotations

from typing import Any


def _coerce_scalar_float(value: Any, default: float = 0.0) -> float:
    try:
        import numpy as np  # type: ignore
    except Exception:
        try:
            return float(value)
        except Exception:
            return float(default)

    try:
        arr = np.asarray(value, dtype=float).reshape(-1)
    except Exception:
        try:
            return float(value)
        except Exception:
            return float(default)
    if arr.size == 0:
        return float(default)
    return float(arr[0])


def lightweight_audio_features(path: str) -> dict[str, Any]:
    """Optional audio features.

    Imports are lazy so core installs stay lightweight.

    Install:
      uv sync --frozen --extra cpu --extra audio
    """
    try:
        import librosa  # type: ignore
        import numpy as np  # type: ignore
    except Exception as e:
        raise RuntimeError("Audio features require the locked `audio` capability in the active uv profile.") from e

    y, sr = librosa.load(path, sr=None, mono=True)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    rms = float(np.mean(librosa.feature.rms(y=y)))
    centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
    duration = float(librosa.get_duration(y=y, sr=sr))

    return {
        "duration_s": duration,
        "bpm": _coerce_scalar_float(tempo),
        "rms": rms,
        "spectral_centroid": centroid,
    }
