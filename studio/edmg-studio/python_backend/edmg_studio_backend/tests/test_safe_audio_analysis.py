from __future__ import annotations

import builtins
import io
import math
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from edmg_studio_backend import app as backend_app
from edmg_studio_backend.services import safe_audio_analysis


class _FakeFFmpegProcess:
    def __init__(
        self, pcm: bytes, *, return_code: int = 0, stderr_file=None, stderr_text: str = ""
    ) -> None:
        self.stdout = io.BytesIO(pcm)
        self._return_code = int(return_code)
        self.killed = False
        if stderr_file is not None and stderr_text:
            stderr_file.write(stderr_text.encode("utf-8"))
            stderr_file.flush()

    def poll(self) -> int:
        return self._return_code

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self._return_code

    def kill(self) -> None:
        self.killed = True


def _write_placeholder_wave(path: Path, *, sample_rate_hz: int = 22_050) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate_hz)
        output.writeframes(b"\x00\x00" * sample_rate_hz)


def _pulse_train_pcm(
    *, sample_rate_hz: int = 22_050, duration_s: float = 12.0, bpm: float = 120.0
) -> bytes:
    sample_count = int(round(sample_rate_hz * duration_s))
    time_axis = np.arange(sample_count, dtype=np.float64) / float(sample_rate_hz)
    signal = 0.08 * np.sin(2.0 * math.pi * 440.0 * time_axis)
    beat_interval_samples = max(1, int(round(sample_rate_hz * 60.0 / bpm)))
    click_length = max(8, int(round(sample_rate_hz * 0.035)))
    click = 0.85 * np.hanning(click_length * 2)[:click_length]
    for start in range(0, sample_count, beat_interval_samples):
        end = min(sample_count, start + click_length)
        signal[start:end] += click[: end - start]
    return np.asarray(np.clip(signal, -1.0, 1.0) * 32767.0, dtype="<i2").tobytes()


def test_ffmpeg_numpy_analyzer_returns_full_feature_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio_path = tmp_path / "input.wav"
    _write_placeholder_wave(audio_path)
    pcm = _pulse_train_pcm()

    monkeypatch.setattr(safe_audio_analysis, "ensure_ffmpeg", lambda _path: "C:/bundled/ffmpeg.exe")

    def fake_popen(command, **kwargs):
        assert command[0] == "C:/bundled/ffmpeg.exe"
        assert command[-2:] == ["s16le", "pipe:1"]
        assert kwargs["shell"] is False
        assert kwargs["stdout"] == subprocess.PIPE
        return _FakeFFmpegProcess(pcm, stderr_file=kwargs["stderr"])

    monkeypatch.setattr(safe_audio_analysis.subprocess, "Popen", fake_popen)

    features = safe_audio_analysis.analyze_audio_ffmpeg_numpy(
        audio_path,
        ffmpeg_path="ffmpeg",
        source="test_decode",
    )

    assert features["duration_s"] == pytest.approx(12.0, abs=0.01)
    assert 100.0 <= features["bpm"] <= 140.0
    assert features["tempo_bpm"] == features["bpm"]
    assert features["beats"]
    assert features["energy"]
    assert features["onset_strength"]
    assert features["onset_times"]
    assert features["spectral_centroid"]
    assert features["spectral_rolloff"]
    assert features["rms_energy"]
    assert len(features["energy"]) == len(features["spectral_centroid"])
    assert features["analysis_backend"] == "ffmpeg_numpy"
    assert features["analysis_source"] == "test_decode"
    assert features["analysis_diagnostics"]["decoder"] == "ffmpeg_pcm_s16le"
    assert features["analysis_diagnostics"]["channels"] == 1
    assert features["analysis_diagnostics"]["decoded_samples"] == 12 * 22_050


def test_ffmpeg_numpy_analyzer_surfaces_decoder_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio_path = tmp_path / "broken.wav"
    _write_placeholder_wave(audio_path)
    pcm = np.zeros(22_050, dtype="<i2").tobytes()
    monkeypatch.setattr(safe_audio_analysis, "ensure_ffmpeg", lambda _path: "ffmpeg.exe")

    def fake_popen(_command, **kwargs):
        return _FakeFFmpegProcess(
            pcm,
            return_code=1,
            stderr_file=kwargs["stderr"],
            stderr_text="invalid data found when processing input",
        )

    monkeypatch.setattr(safe_audio_analysis.subprocess, "Popen", fake_popen)

    with pytest.raises(safe_audio_analysis.SafeAudioAnalysisError, match="invalid data found"):
        safe_audio_analysis.analyze_audio_ffmpeg_numpy(audio_path)


def test_pcm_analyzer_compacts_retained_features_to_memory_bound() -> None:
    sample_rate_hz = 8_000
    pcm = np.zeros(sample_rate_hz * 20, dtype="<i2").tobytes()

    features = safe_audio_analysis._analyze_pcm_stream(
        io.BytesIO(pcm),
        sample_rate_hz=sample_rate_hz,
        frame_size=256,
        hop_size=128,
        max_feature_points=1_000,
    )

    diagnostics = features["_diagnostics"]
    assert diagnostics["analyzed_frame_count"] > 1_000
    assert diagnostics["retained_stride"] == 2
    assert diagnostics["retained_frame_count"] <= 1_000
    assert len(features["energy"]) <= 1_000
    assert features["duration_s"] == pytest.approx(20.0)


def test_collect_audio_features_uses_safe_path_without_importing_enhanced_analyzer_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "windows.wav"
    _write_placeholder_wave(audio_path)
    calls: list[tuple[Path, str, str]] = []

    monkeypatch.setattr(backend_app.platform, "system", lambda: "Windows")

    def fake_safe_analyzer(path, *, ffmpeg_path, source):
        calls.append((Path(path), str(ffmpeg_path), str(source)))
        return {"duration_s": 1.0, "analysis_backend": "ffmpeg_numpy", "analysis_source": source}

    monkeypatch.setattr(backend_app, "analyze_audio_ffmpeg_numpy", fake_safe_analyzer)

    original_import = builtins.__import__

    def reject_enhanced_import(name, *args, **kwargs):
        if name.startswith("enhanced_deforum_music_generator") or name == "edmg_ai_service.audio":
            raise AssertionError(f"Windows-safe analysis imported an unsafe analyzer: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_enhanced_import)

    result = backend_app._collect_audio_analysis_features(audio_path)

    assert result["analysis_backend"] == "ffmpeg_numpy"
    assert calls == [(audio_path, backend_app.settings.ffmpeg_path, "windows_safe_path")]


def test_collect_audio_features_uses_safe_fallback_when_enhanced_analyzer_fails_off_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "fallback.wav"
    _write_placeholder_wave(audio_path)
    monkeypatch.setattr(backend_app.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        backend_app,
        "analyze_audio_ffmpeg_numpy",
        lambda _path, *, ffmpeg_path, source: {
            "duration_s": 1.0,
            "analysis_backend": "ffmpeg_numpy",
            "analysis_source": source,
            "ffmpeg_path_seen": ffmpeg_path,
        },
    )
    original_import = builtins.__import__

    def fail_enhanced_import(name, *args, **kwargs):
        if name.startswith("enhanced_deforum_music_generator"):
            raise ImportError("enhanced analyzer unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_enhanced_import)

    result = backend_app._collect_audio_analysis_features(audio_path)

    assert result["analysis_backend"] == "ffmpeg_numpy"
    assert result["analysis_source"] == "enhanced_analyzer_fallback"
    assert result["ffmpeg_path_seen"] == backend_app.settings.ffmpeg_path
