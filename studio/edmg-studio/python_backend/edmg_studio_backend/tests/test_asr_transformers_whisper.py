from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from edmg_ai_service import asr


class FakeTensor:
    def __init__(self, floating: bool = True):
        self.floating = floating
        self.to_calls: list[dict[str, object]] = []

    def is_floating_point(self) -> bool:
        return self.floating

    def to(self, **kwargs):
        self.to_calls.append(kwargs)
        return self


def test_provider_normalization_and_explicit_selection(monkeypatch):
    assert asr._normalize_provider("transformers-whisper") == "transformers_whisper"
    assert asr._normalize_provider("hf_whisper") == "transformers_whisper"
    sentinel = {"text": "local transcript"}
    calls = []
    monkeypatch.setattr(
        asr,
        "_transcribe_transformers_whisper",
        lambda path, model_path, **kwargs: calls.append((path, model_path, kwargs)) or sentinel,
    )

    result = asr.transcribe_detailed(
        "audio.wav", model_size=r"C:\models\whisper", provider="transformers_whisper", device="cuda:1"
    )

    assert result is sentinel
    assert calls == [("audio.wav", r"C:\models\whisper", {"device": "cuda:1", "cancel_check": None})]


def test_model_loading_is_local_only_and_uses_cpu_float32(monkeypatch, tmp_path):
    calls = {}

    class Processor:
        @staticmethod
        def from_pretrained(path, **kwargs):
            calls["processor"] = (path, kwargs)
            return object()

    class LoadedModel:
        def to(self, device):
            calls["device"] = device
            return self

        def eval(self):
            calls["eval"] = True

    class Model:
        @staticmethod
        def from_pretrained(path, **kwargs):
            calls["model"] = (path, kwargs)
            return LoadedModel()

    torch = SimpleNamespace(float16="fp16", float32="fp32")
    transformers = SimpleNamespace(AutoProcessor=Processor, AutoModelForSpeechSeq2Seq=Model)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    asr._load_transformers_whisper_model.cache_clear()

    asr._load_transformers_whisper_model(str(tmp_path), "cpu")

    assert calls["processor"][1] == {"local_files_only": True, "trust_remote_code": False}
    assert calls["model"][1] == {
        "local_files_only": True,
        "trust_remote_code": False,
        "torch_dtype": "fp32",
    }
    assert calls["device"] == "cpu"
    assert calls["eval"] is True
    asr._load_transformers_whisper_model.cache_clear()


def test_output_mapping_cuda_dtype_and_language(monkeypatch, tmp_path):
    feature = FakeTensor()
    generated = object()

    class Processor:
        def __call__(self, audio, **kwargs):
            assert list(audio) == [0.0] * 32000
            assert kwargs == {"sampling_rate": 16000, "return_tensors": "pt"}
            return {"input_features": feature}

        def batch_decode(self, value, *, skip_special_tokens, decode_with_timestamps=False):
            assert value is generated
            if decode_with_timestamps:
                return ["<|0.00|> Hello<|1.25|> world<|2.00|>"]
            return ["Hello world" if skip_special_tokens else "<|en|><|transcribe|>Hello world"]

    class Model:
        def generate(self, **kwargs):
            assert kwargs["input_features"] is feature
            assert kwargs["return_timestamps"] is True
            return generated

    class InferenceMode:
        def __enter__(self):
            return None

        def __exit__(self, *_args):
            return False

    torch = SimpleNamespace(
        float16="fp16", float32="fp32", inference_mode=lambda: InferenceMode(),
        cuda=SimpleNamespace(is_available=lambda: True, device_count=lambda: 2),
    )
    librosa = SimpleNamespace(load=lambda path, sr, mono: ([0.0] * 32000, sr))
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "librosa", librosa)
    monkeypatch.setattr(asr, "_load_transformers_whisper_model", lambda path, device: (Processor(), Model()))

    result = asr._transcribe_transformers_whisper(
        "audio.wav", str(tmp_path), device="cuda:1"
    )

    assert feature.to_calls == [{"device": "cuda:1", "dtype": "fp16"}]
    assert result["text"] == "Hello world"
    assert result["language"] == "en"
    assert result["segments"] == [
        {"start": 0.0, "end": 1.25, "text": "Hello"},
        {"start": 1.25, "end": 2.0, "text": "world"},
    ]
    assert result["duration_s"] == 2.0
    assert result["provider"] == "transformers_whisper"
    assert result["compute_type"] == "float16"


def test_device_validation_and_cancellation(monkeypatch, tmp_path):
    torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: False, device_count=lambda: 0)
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    assert asr._normalize_transformers_device("auto") == "cpu"
    with pytest.raises(RuntimeError, match="unavailable CUDA device cuda:0"):
        asr._normalize_transformers_device("cuda:0")
    with pytest.raises(RuntimeError, match="cancelled"):
        asr._transcribe_transformers_whisper(
            "audio.wav", str(tmp_path), cancel_check=lambda: True
        )


def test_faster_whisper_selection_is_retained(monkeypatch):
    expected = {"text": "existing provider"}
    calls = []
    monkeypatch.setattr(
        asr,
        "_transcribe_faster_whisper",
        lambda path, **kwargs: calls.append((path, kwargs)) or expected,
    )

    result = asr.transcribe_detailed("audio.wav", model_size="turbo", provider="whisper")

    assert result is expected
    assert calls == [("audio.wav", {"model_size": "turbo", "device": "cpu", "compute_type": "int8"})]
