from __future__ import annotations

import asyncio
import os
import numpy as np
import pytest
import soundfile as sf
import librosa
from types import SimpleNamespace

from enhanced_deforum_music_generator import config_system_complete
from enhanced_deforum_music_generator.config.config_system import AudioConfig
from enhanced_deforum_music_generator.config.config_system import LyricsConfig
from enhanced_deforum_music_generator.core.audio_analyzer import AudioAnalyzer
from enhanced_deforum_music_generator.core import lyrics_analyzer as lyrics_analyzer_module
from enhanced_deforum_music_generator.optimized_components import create_optimized_analyzer
from edmg_ai_service import app as ai_service_app
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


def test_transcribe_detailed_returns_segment_metadata(monkeypatch):
    class FakeInfo:
        duration = 612.4
        duration_after_vad = 598.2
        language = "en"

    class FakeSegment:
        def __init__(self, start, end, text):
            self.start = start
            self.end = end
            self.text = text
            self.no_speech_prob = 0.02
            self.avg_logprob = -0.2

    class FakeModel:
        def transcribe(self, *args, **kwargs):
            assert kwargs["without_timestamps"] is False
            return iter((
                FakeSegment(0.0, 4.2, "First long-form section."),
                FakeSegment(302.0, 307.5, "Middle transcript cue."),
                FakeSegment(594.0, 598.2, "Final transcript cue."),
            )), FakeInfo()

    monkeypatch.setattr(asr_module, "_load_model", lambda model_size: FakeModel())

    result = asr_module.transcribe_detailed("longform.wav", model_size="small")

    assert result["language"] == "en"
    assert result["duration_s"] == pytest.approx(612.4)
    assert result["duration_after_vad_s"] == pytest.approx(598.2)
    assert result["segment_count"] == 3
    assert result["word_count"] >= 6
    assert result["text"].startswith("First long-form section.")
    assert result["segments"][1]["start"] == pytest.approx(302.0)
    assert result["segments"][2]["text"] == "Final transcript cue."


def test_long_form_audio_defaults_allow_30_minutes():
    assert config_system_complete.AudioConfig().max_duration == 1800
    assert config_system_complete.AudioConfigModel().max_duration == 1800
    assert create_optimized_analyzer().max_duration == 1800


def test_ai_service_upload_helper_streams_chunks_to_tempfile():
    class FakeUpload:
        def __init__(self, chunks):
            self._chunks = list(chunks)
            self.closed = False

        async def read(self, _chunk_size: int = -1):
            if self._chunks:
                return self._chunks.pop(0)
            return b""

        async def close(self):
            self.closed = True

    upload = FakeUpload([b"ab", b"cdef", b"ghi"])
    tmp_path_str = asyncio.run(
        ai_service_app._persist_upload_to_tempfile(upload, suffix=".wav", chunk_size=2)
    )

    try:
        assert os.path.exists(tmp_path_str)
        with open(tmp_path_str, "rb") as handle:
            assert handle.read() == b"abcdefghi"
        assert upload.closed is True
    finally:
        if os.path.exists(tmp_path_str):
            os.remove(tmp_path_str)


def test_lyric_analyzer_accepts_modern_lyrics_config(monkeypatch):
    class FakeWhisperModel:
        def transcribe(self, audio_file, **kwargs):
            assert audio_file == "song.wav"
            assert kwargs["language"] == "en"
            return {"text": "long form spoken word transcript"}

    loaded = {}

    def fake_load_model(model_name: str):
        loaded["model_name"] = model_name
        return FakeWhisperModel()

    monkeypatch.setattr(lyrics_analyzer_module, "WHISPER_AVAILABLE", True)
    monkeypatch.setattr(
        lyrics_analyzer_module,
        "whisper",
        SimpleNamespace(load_model=fake_load_model),
        raising=False,
    )

    analyzer = lyrics_analyzer_module.LyricAnalyzer(
        LyricsConfig(provider="whisper", model="tiny", language="en")
    )

    assert loaded["model_name"] == "tiny"
    assert analyzer._transcribe_audio("song.wav") == "long form spoken word transcript"
