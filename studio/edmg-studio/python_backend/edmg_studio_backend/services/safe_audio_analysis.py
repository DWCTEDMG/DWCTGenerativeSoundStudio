from __future__ import annotations

import math
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, BinaryIO

from .ffmpeg import ensure_ffmpeg


class SafeAudioAnalysisError(RuntimeError):
    """Raised when the isolated FFmpeg audio decode or analysis cannot complete."""


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _normalize_curve(values: Any) -> list[float]:
    try:
        import numpy as np  # type: ignore
    except Exception as exc:  # pragma: no cover - exercised by capability packaging checks
        raise SafeAudioAnalysisError("Safe audio analysis requires NumPy.") from exc

    array = np.asarray(values, dtype=np.float64).reshape(-1)
    if array.size == 0:
        return []
    array = np.nan_to_num(array, nan=0.0, posinf=0.0, neginf=0.0)
    minimum = float(array.min())
    maximum = float(array.max())
    if maximum > minimum:
        array = (array - minimum) / (maximum - minimum)
    elif maximum > 0.0:
        array = np.ones_like(array)
    else:
        array = np.zeros_like(array)
    return [float(value) for value in np.clip(array, 0.0, 1.0)]


def _tempo_and_beats(
    onset_strength: Any, *, frame_step_s: float, duration_s: float
) -> tuple[float, list[float], float]:
    """Estimate tempo from a small onset envelope without librosa/numba/llvmlite."""

    import numpy as np  # type: ignore

    envelope = np.asarray(onset_strength, dtype=np.float64).reshape(-1)
    if envelope.size < 8 or frame_step_s <= 0.0:
        return 0.0, [], 0.0
    envelope = np.nan_to_num(envelope, nan=0.0, posinf=0.0, neginf=0.0)
    envelope = np.maximum(envelope - float(np.median(envelope)), 0.0)
    envelope -= float(envelope.mean())
    energy = float(np.dot(envelope, envelope))
    if energy <= 1e-12:
        return 0.0, [], 0.0

    # FFT autocorrelation keeps the work O(n log n), unlike np.correlate's
    # quadratic full-song path.
    fft_size = 1 << max(1, (2 * int(envelope.size) - 1).bit_length())
    spectrum = np.fft.rfft(envelope, n=fft_size)
    autocorrelation = np.fft.irfft(spectrum * np.conjugate(spectrum), n=fft_size)[: envelope.size]
    if not math.isfinite(float(autocorrelation[0])) or float(autocorrelation[0]) <= 1e-12:
        return 0.0, [], 0.0
    autocorrelation /= float(autocorrelation[0])

    min_bpm = 50.0
    max_bpm = 200.0
    min_lag = max(1, int(round(60.0 / (max_bpm * frame_step_s))))
    max_lag = min(int(envelope.size) - 1, int(round(60.0 / (min_bpm * frame_step_s))))
    if max_lag <= min_lag:
        return 0.0, [], 0.0

    best_lag = min_lag
    best_score = -math.inf
    for lag in range(min_lag, max_lag + 1):
        bpm = 60.0 / (float(lag) * frame_step_s)
        score = float(autocorrelation[lag])
        if lag * 2 < autocorrelation.size:
            score += 0.35 * float(autocorrelation[lag * 2])
        if lag // 2 >= min_lag:
            score += 0.15 * float(autocorrelation[lag // 2])
        # A broad musical-tempo prior only resolves octave ambiguity; the
        # autocorrelation still dominates the estimate.
        score *= math.exp(-0.5 * (math.log2(max(bpm, 1e-6) / 120.0) / 1.25) ** 2)
        if score > best_score:
            best_lag = lag
            best_score = score

    tempo_bpm = 60.0 / (float(best_lag) * frame_step_s)
    confidence = max(0.0, min(1.0, float(autocorrelation[best_lag])))
    if confidence < 0.03 or not (min_bpm <= tempo_bpm <= max_bpm):
        return 0.0, [], confidence

    positive_envelope = np.maximum(np.asarray(onset_strength, dtype=np.float64), 0.0)
    phase_scores = np.zeros(best_lag, dtype=np.float64)
    for phase in range(best_lag):
        phase_scores[phase] = float(positive_envelope[phase::best_lag].sum())
    phase = int(np.argmax(phase_scores))
    beats: list[float] = []
    index = phase
    while index < positive_envelope.size:
        timestamp = float(index) * frame_step_s
        if timestamp <= duration_s + 1e-6:
            beats.append(timestamp)
        index += best_lag
    return float(tempo_bpm), beats, confidence


def _onset_times(onset_strength: Any, *, frame_step_s: float, duration_s: float) -> list[float]:
    import numpy as np  # type: ignore

    envelope = np.asarray(onset_strength, dtype=np.float64).reshape(-1)
    if envelope.size < 3 or frame_step_s <= 0.0:
        return []
    envelope = np.nan_to_num(envelope, nan=0.0, posinf=0.0, neginf=0.0)
    normalized = np.asarray(_normalize_curve(envelope), dtype=np.float64)
    threshold = max(0.12, float(np.median(normalized) + 0.35 * np.std(normalized)))
    minimum_gap_frames = max(1, int(round(0.08 / frame_step_s)))
    peaks: list[int] = []
    for index in range(1, int(normalized.size) - 1):
        value = float(normalized[index])
        if (
            value < threshold
            or value < float(normalized[index - 1])
            or value <= float(normalized[index + 1])
        ):
            continue
        if peaks and index - peaks[-1] < minimum_gap_frames:
            if value > float(normalized[peaks[-1]]):
                peaks[-1] = index
            continue
        peaks.append(index)
    return [
        min(float(duration_s), float(index) * frame_step_s)
        for index in peaks
        if float(index) * frame_step_s <= duration_s + 1e-6
    ]


def _analyze_pcm_stream(
    stream: BinaryIO,
    *,
    sample_rate_hz: int,
    frame_size: int,
    hop_size: int,
    max_feature_points: int,
    read_size_bytes: int = 256 * 1024,
) -> dict[str, Any]:
    """Analyze mono signed-16-bit PCM while retaining only frame summaries."""

    try:
        import numpy as np  # type: ignore
    except Exception as exc:
        raise SafeAudioAnalysisError("Safe audio analysis requires NumPy.") from exc

    if sample_rate_hz < 8_000:
        raise ValueError("sample_rate_hz must be at least 8000")
    if frame_size < 256 or hop_size < 1 or hop_size > frame_size:
        raise ValueError("frame_size and hop_size do not describe a valid analysis window")
    if max_feature_points < 1_000:
        raise ValueError("max_feature_points must be at least 1000")

    window = np.hanning(frame_size).astype(np.float32)
    frequencies = np.fft.rfftfreq(frame_size, d=1.0 / float(sample_rate_hz))
    sample_buffer = np.empty(0, dtype=np.float32)
    byte_remainder = b""
    decoded_samples = 0
    analyzed_frame_count = 0
    retained_stride = 1
    previous_spectrum: Any = None
    energy_values: list[float] = []
    rms_values: list[float] = []
    onset_values: list[float] = []
    centroid_values: list[float] = []
    rolloff_values: list[float] = []

    def compact_if_needed() -> None:
        nonlocal retained_stride, previous_spectrum
        if len(energy_values) < max_feature_points:
            return
        energy_values[:] = energy_values[::2]
        rms_values[:] = rms_values[::2]
        onset_values[:] = onset_values[::2]
        centroid_values[:] = centroid_values[::2]
        rolloff_values[:] = rolloff_values[::2]
        retained_stride *= 2
        previous_spectrum = None

    def analyze_frame(frame: Any) -> None:
        nonlocal analyzed_frame_count, previous_spectrum
        frame_index = analyzed_frame_count
        analyzed_frame_count += 1
        if frame_index % retained_stride != 0:
            return
        compact_if_needed()
        # Compaction may have changed the stride for this frame.
        if frame_index % retained_stride != 0:
            return

        frame_array = np.asarray(frame, dtype=np.float32)
        rms = float(np.sqrt(np.mean(np.square(frame_array, dtype=np.float64))))
        mean_absolute = float(np.mean(np.abs(frame_array)))
        magnitude = np.abs(np.fft.rfft(frame_array * window)).astype(np.float64)
        magnitude_sum = float(magnitude.sum())
        if magnitude_sum > 1e-12:
            centroid = float(np.dot(frequencies, magnitude) / magnitude_sum)
            cumulative = np.cumsum(magnitude)
            rolloff_index = int(np.searchsorted(cumulative, 0.85 * magnitude_sum, side="left"))
            rolloff = float(frequencies[min(rolloff_index, frequencies.size - 1)])
        else:
            centroid = 0.0
            rolloff = 0.0
        if previous_spectrum is None or previous_spectrum.shape != magnitude.shape:
            spectral_flux = 0.0
        else:
            spectral_flux = float(
                np.maximum(magnitude - previous_spectrum, 0.0).sum()
                / (float(previous_spectrum.sum()) + 1e-12)
            )
        previous_spectrum = magnitude
        previous_rms = rms_values[-1] if rms_values else rms
        onset = max(0.0, rms - previous_rms) + spectral_flux
        energy_values.append(_finite_float(mean_absolute))
        rms_values.append(_finite_float(rms))
        onset_values.append(_finite_float(onset))
        centroid_values.append(_finite_float(centroid))
        rolloff_values.append(_finite_float(rolloff))

    while True:
        chunk = stream.read(read_size_bytes)
        if not chunk:
            break
        raw = byte_remainder + chunk
        usable_length = len(raw) - (len(raw) % 2)
        byte_remainder = raw[usable_length:]
        if usable_length <= 0:
            continue
        samples = np.frombuffer(raw[:usable_length], dtype="<i2").astype(np.float32)
        samples /= 32768.0
        decoded_samples += int(samples.size)
        sample_buffer = np.concatenate((sample_buffer, samples))
        while sample_buffer.size >= frame_size:
            analyze_frame(sample_buffer[:frame_size])
            sample_buffer = sample_buffer[hop_size:]

    if byte_remainder:
        raise SafeAudioAnalysisError("FFmpeg returned a truncated signed-16-bit PCM sample.")
    if decoded_samples <= 0:
        raise SafeAudioAnalysisError("FFmpeg decoded no audio samples from the selected file.")
    if analyzed_frame_count == 0:
        padded = np.zeros(frame_size, dtype=np.float32)
        padded[: sample_buffer.size] = sample_buffer
        analyze_frame(padded)

    duration_s = float(decoded_samples) / float(sample_rate_hz)
    frame_step_s = float(hop_size * retained_stride) / float(sample_rate_hz)
    normalized_onsets = _normalize_curve(onset_values)
    tempo_bpm, beats, bpm_confidence = _tempo_and_beats(
        normalized_onsets,
        frame_step_s=frame_step_s,
        duration_s=duration_s,
    )
    return {
        "duration_s": duration_s,
        "bpm": tempo_bpm,
        "tempo_bpm": tempo_bpm,
        "bpm_confidence": bpm_confidence,
        "beats": beats,
        "energy": _normalize_curve(energy_values),
        "onset_strength": normalized_onsets,
        "onset_times": _onset_times(
            normalized_onsets, frame_step_s=frame_step_s, duration_s=duration_s
        ),
        "spectral_centroid": [_finite_float(value) for value in centroid_values],
        "spectral_rolloff": [_finite_float(value) for value in rolloff_values],
        "rms_energy": _normalize_curve(rms_values),
        "sample_rate": int(sample_rate_hz),
        "_diagnostics": {
            "decoded_samples": int(decoded_samples),
            "analyzed_frame_count": int(analyzed_frame_count),
            "retained_frame_count": int(len(energy_values)),
            "retained_stride": int(retained_stride),
            "effective_frame_step_s": frame_step_s,
        },
    }


def analyze_audio_ffmpeg_numpy(
    audio_path: str | Path,
    *,
    ffmpeg_path: str = "ffmpeg",
    source: str = "safe_fallback",
    sample_rate_hz: int = 22_050,
    frame_size: int = 2_048,
    hop_size: int = 1_024,
    max_feature_points: int = 120_000,
    timeout_s: float = 900.0,
) -> dict[str, Any]:
    """Decode audio out-of-process and derive bounded-memory NumPy features.

    In particular, this path does not import librosa, numba, or llvmlite. That
    makes it suitable for Windows builds where a native failure in those
    libraries would terminate the entire FastAPI process before Python could
    catch an exception.
    """

    path = Path(audio_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise SafeAudioAnalysisError(f"Audio input is not a file: {path}")
    resolved_ffmpeg = ensure_ffmpeg(ffmpeg_path)
    command = [
        resolved_ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-ac",
        "1",
        "-ar",
        str(int(sample_rate_hz)),
        "-acodec",
        "pcm_s16le",
        "-f",
        "s16le",
        "pipe:1",
    ]
    creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0
    timed_out = threading.Event()

    with tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            shell=False,
            creationflags=creation_flags,
        )
        if process.stdout is None:  # pragma: no cover - subprocess contract guard
            process.kill()
            raise SafeAudioAnalysisError("FFmpeg did not provide a PCM output stream.")

        def terminate_on_timeout() -> None:
            if process.poll() is None:
                timed_out.set()
                process.kill()

        watchdog = threading.Timer(max(1.0, float(timeout_s)), terminate_on_timeout)
        watchdog.daemon = True
        watchdog.start()
        analysis: dict[str, Any] | None = None
        analysis_error: BaseException | None = None
        try:
            analysis = _analyze_pcm_stream(
                process.stdout,
                sample_rate_hz=int(sample_rate_hz),
                frame_size=int(frame_size),
                hop_size=int(hop_size),
                max_feature_points=int(max_feature_points),
            )
        except BaseException as exc:
            analysis_error = exc
            if process.poll() is None:
                process.kill()
        finally:
            process.stdout.close()
            try:
                return_code = process.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                process.kill()
                return_code = process.wait(timeout=10.0)
            watchdog.cancel()

        stderr_file.seek(0)
        stderr_text = stderr_file.read(16_384).decode("utf-8", errors="replace").strip()
        if timed_out.is_set():
            raise SafeAudioAnalysisError(
                f"FFmpeg audio analysis exceeded the {float(timeout_s):g}-second safety timeout."
            )
        if analysis_error is not None:
            if isinstance(analysis_error, SafeAudioAnalysisError):
                raise analysis_error
            raise SafeAudioAnalysisError(
                "Safe audio feature calculation failed."
            ) from analysis_error
        if return_code != 0:
            detail = stderr_text or f"exit code {return_code}"
            raise SafeAudioAnalysisError(f"FFmpeg could not decode the selected audio: {detail}")
        if analysis is None:  # pragma: no cover - defensive state guard
            raise SafeAudioAnalysisError("Safe audio analysis produced no result.")

    stream_diagnostics = dict(analysis.pop("_diagnostics", {}) or {})
    analysis["analysis_backend"] = "ffmpeg_numpy"
    analysis["analysis_source"] = str(source or "safe_fallback")
    analysis["analysis_diagnostics"] = {
        "backend": "ffmpeg_numpy",
        "source": str(source or "safe_fallback"),
        "decoder": "ffmpeg_pcm_s16le",
        "ffmpeg_executable": str(resolved_ffmpeg),
        "sample_rate_hz": int(sample_rate_hz),
        "channels": 1,
        "frame_size": int(frame_size),
        "hop_size": int(hop_size),
        "max_feature_points": int(max_feature_points),
        **stream_diagnostics,
    }
    return analysis
