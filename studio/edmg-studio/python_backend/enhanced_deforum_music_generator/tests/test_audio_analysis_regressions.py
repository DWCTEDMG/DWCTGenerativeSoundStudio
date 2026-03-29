from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf
import librosa

from enhanced_deforum_music_generator.config.config_system import AudioConfig
from enhanced_deforum_music_generator.core.audio_analyzer import AudioAnalyzer
from edmg_ai_service.audio import lightweight_audio_features
from edmg_ai_service import asr as asr_module


def _write_test_tone(tmp_path, *, duration_s: float = 2.0, sr: int = 22050):
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    y = 0.4 * np.sin(2 * np.pi * 220.0 * t)
    audio_path = tmp_path / "tone.wav"
    sf.write(audio_path, y, sr)
    return audio_path, y, sr


def test_audio_analyzer_handles_array_tempo_and_time_unit_beats(monkeypatch, tmp_path):
    audio_path, _y, sr = _write_test_tone(tmp_path)

    def fake_beat_track(*args, **kwargs):
        assert kwargs["units"] == "time"
        return np.array([86.1328125]), np.array([0.5, 1.0, 1.5], dtype=float)

    monkeypatch.setattr(librosa.beat, "beat_track", fake_beat_track)

    analyzer = AudioAnalyzer(AudioConfig(max_duration=5, beat_track_units="time"))
    features = analyzer.analyze_features(str(audio_path), enable_cache=False)

    assert features.tempo == pytest.approx(86.1328125)
    assert features.beats == pytest.approx([0.5, 1.0, 1.5])
    assert features.beat_frames == librosa.time_to_frames(np.array([0.5, 1.0, 1.5]), sr=sr).tolist()


def test_lightweight_audio_features_handles_array_tempo(monkeypatch, tmp_path):
    audio_path, _y, _sr = _write_test_tone(tmp_path)

    def fake_beat_track(*args, **kwargs):
        return np.array([128.0]), np.array([5, 10, 15], dtype=int)

    monkeypatch.setattr(librosa.beat, "beat_track", fake_beat_track)

    features = lightweight_audio_features(str(audio_path))

    assert features["bpm"] == pytest.approx(128.0)
    assert features["duration_s"] > 0


def test_transcribe_returns_empty_string_when_vad_finds_no_speech(monkeypatch):
    class FakeInfo:
        duration_after_vad = 0.0

    class FakeModel:
        def transcribe(self, *args, **kwargs):
            return iter(()), FakeInfo()

    monkeypatch.setattr(asr_module, "_load_model", lambda model_size: FakeModel())

    assert asr_module.transcribe("instrumental.wav", model_size="small") == ""


def test_transcribe_filters_short_low_confidence_hallucinations(monkeypatch):
    class FakeInfo:
        duration_after_vad = 0.8

    class FakeSegment:
        text = "uh"
        no_speech_prob = 0.95
        avg_logprob = -1.6

    class FakeModel:
        def transcribe(self, *args, **kwargs):
            return iter((FakeSegment(),)), FakeInfo()

    monkeypatch.setattr(asr_module, "_load_model", lambda model_size: FakeModel())

    assert asr_module.transcribe("instrumental.wav", model_size="small") == ""
