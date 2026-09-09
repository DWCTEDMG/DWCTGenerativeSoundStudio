from pathlib import Path

import pytest

from edmg_studio_backend import asr_cuda


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(asr_cuda.sys, "platform", "win32")
    monkeypatch.setattr(asr_cuda, "_handles", [])
    monkeypatch.setattr(asr_cuda, "_loaded_paths", ())
    incomplete, complete = tmp_path / "incomplete", tmp_path / "complete"
    incomplete.mkdir()
    complete.mkdir()
    (incomplete / "cublas64_12.dll").touch()
    for name in asr_cuda._LIBRARIES:
        (complete / name).touch()
    monkeypatch.setattr(asr_cuda, "_candidate_directories", lambda: [incomplete, complete])
    return complete


def test_preloads_only_complete_pair_once_without_changing_path(runtime, monkeypatch):
    calls = []
    before = asr_cuda.os.environ.get("PATH")
    monkeypatch.setattr(asr_cuda.ctypes, "WinDLL", lambda path: calls.append(path) or object(), raising=False)
    loaded = asr_cuda.preload_cuda12_cublas()
    assert tuple(calls) == loaded == tuple(str((runtime / name).resolve()) for name in asr_cuda._LIBRARIES)
    assert all(Path(path).is_absolute() for path in loaded)
    assert asr_cuda.preload_cuda12_cublas() == loaded
    assert len(calls) == len(asr_cuda._handles) == 2
    assert asr_cuda.os.environ.get("PATH") == before


def test_missing_pair_has_actionable_error_and_never_loads(runtime, monkeypatch):
    monkeypatch.setattr(asr_cuda, "_candidate_directories", lambda: [runtime.parent / "incomplete"])
    monkeypatch.setattr(asr_cuda.ctypes, "WinDLL", lambda _: pytest.fail("Incomplete pair must not load"), raising=False)
    with pytest.raises(RuntimeError, match="CUDA 13 Torch/TensorRT profile can remain selected"):
        asr_cuda.preload_cuda12_cublas()


def test_load_failure_does_not_try_a_different_toolkit(runtime, monkeypatch):
    calls = []

    def load(path):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("DLL dependencies missing")
        return object()

    monkeypatch.setattr(asr_cuda.ctypes, "WinDLL", load, raising=False)
    with pytest.raises(RuntimeError, match="DLL dependencies missing"):
        asr_cuda.preload_cuda12_cublas()
    assert len(calls) == 2
    assert not asr_cuda._handles
    assert not asr_cuda._loaded_paths
