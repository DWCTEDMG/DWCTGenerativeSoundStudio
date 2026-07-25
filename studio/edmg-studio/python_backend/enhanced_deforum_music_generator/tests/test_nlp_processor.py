import sys
import types

import pytest
from enhanced_deforum_music_generator.config.config_system import LyricsConfig
from enhanced_deforum_music_generator.core.nlp_processor import LyricsProcessor


def test_whisper_loads_model(monkeypatch):
    cfg = LyricsConfig(provider="whisper", model="tiny")
    processor = LyricsProcessor(cfg)

    class FakeModel:
        def transcribe(self, path):
            return {"segments": [{"start": 0.0, "end": 1.0, "text": "hello"}]}

    monkeypatch.setitem(sys.modules, "whisper", types.SimpleNamespace(load_model=lambda m: FakeModel()))
    result = processor.transcribe("fake_audio.wav")

    assert isinstance(result, list)
    assert result[0]["text"] == "hello"
