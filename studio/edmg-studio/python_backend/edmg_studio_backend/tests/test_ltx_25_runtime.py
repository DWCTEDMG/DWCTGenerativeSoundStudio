from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from edmg_studio_backend.services import internal_video_models as ivm
from edmg_studio_backend.services import ltx_25_runtime as ltx
from edmg_studio_backend.services.model_runtime_registry import create_default_registry


def _package(root: Path) -> Path:
    for _flag, relative in ltx._COMPONENT_FLAGS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"model")
    return root


def test_build_command_uses_exact_components_and_official_flags(tmp_path: Path) -> None:
    root = _package(tmp_path / "model")
    image = tmp_path / "input.png"
    image.write_bytes(b"image")
    command = ltx.build_command(
        package_root=root,
        output_path=tmp_path / "output.mp4",
        prompt="subject; no shell expansion",
        width=768,
        height=512,
        num_frames=17,
        fps=24,
        seed=123,
        image_path=image,
        offload="cpu",
        fp8=True,
    )

    assert command[1:3] == ["-m", "ltx_pipelines.distilled"]
    for flag, relative in ltx._COMPONENT_FLAGS:
        assert command[command.index(flag) + 1] == str((root / relative).resolve())
    assert command[command.index("--prompt") + 1] == "subject; no shell expansion"
    assert command[command.index("--frame-rate") + 1] == "24.0"
    assert command[command.index("--image") + 2:] == ["0", "1.0", "--quantization", "fp8-cast"]
    assert "--offload" in command and command[command.index("--offload") + 1] == "cpu"


def test_device_environment_isolates_selected_gpu(monkeypatch) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "8")
    assert ltx._device_environment("cuda:3")["CUDA_VISIBLE_DEVICES"] == "3"
    with pytest.raises(Exception, match="Unsupported LTX-2.5 device"):
        ltx._device_environment("cpu")
    with pytest.raises(Exception, match="Unsupported LTX-2.5 device"):
        ltx._device_environment("mps")


def test_runtime_version_is_fixed_to_qualified_release(monkeypatch) -> None:
    monkeypatch.setenv("EDMG_LTX25_VERSION", "0.0.1")
    monkeypatch.setattr(
        ltx,
        "runtime_identity",
        lambda: {"python": "python", "ltx_pipelines_version": ltx.LTX_PIPELINES_VERSION},
    )

    ltx.validate_runtime_version()


def test_generate_runs_isolated_cli_and_cleans_files(tmp_path: Path, monkeypatch) -> None:
    root = _package(tmp_path / "model")
    captured: dict = {}
    monkeypatch.setattr(ltx, "validate_runtime_version", lambda: None)

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        Path(command[command.index("--output-path") + 1]).write_bytes(b"mp4")
        return "", ""

    monkeypatch.setattr(ltx, "_run", fake_run)
    monkeypatch.setattr(ltx, "decode_mp4", lambda path: [Image.new("RGB", (64, 64))])
    frames = ltx.generate_ltx_frames(
        package_root=root,
        workspace=tmp_path / "work",
        prompt="smoke",
        width=64,
        height=64,
        num_frames=9,
        fps=8,
        seed=7,
        device="cuda:2",
        init_image=Image.new("RGB", (64, 64)),
        cpu_offload=True,
        fp8=True,
        timeout_s=12,
    )

    assert len(frames) == 1
    assert captured["env"]["CUDA_VISIBLE_DEVICES"] == "2"
    assert captured["timeout_s"] == 12
    assert not list((tmp_path / "work").glob("ltx25-*"))


class _WaitingProcess:
    pid = 42
    returncode = None

    def communicate(self, timeout):
        raise subprocess.TimeoutExpired("ltx", timeout)

    def poll(self):
        return None


def test_timeout_kills_process_tree(monkeypatch) -> None:
    process = _WaitingProcess()
    killed = []
    ticks = iter((0.0, 0.0, 2.0))
    monkeypatch.setattr(ltx.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(ltx.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(ltx, "_terminate_process_tree", lambda value: killed.append(value))

    with pytest.raises(TimeoutError, match="exceeded"):
        ltx._run(["python", "-m", "ltx_pipelines.distilled"], env={}, timeout_s=1, cancel_check=None)
    assert killed == [process]


def test_cancellation_kills_process_tree(monkeypatch) -> None:
    process = _WaitingProcess()
    killed = []
    monkeypatch.setattr(ltx.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(ltx, "_terminate_process_tree", lambda value: killed.append(value))

    with pytest.raises(RuntimeError, match="cancelled"):
        ltx._run(["python"], env={}, timeout_s=10, cancel_check=lambda: True)
    assert killed == [process]


def test_nonzero_exit_surfaces_stderr(monkeypatch) -> None:
    process = SimpleNamespace(
        pid=7,
        returncode=2,
        communicate=lambda timeout: ("", "CUDA allocation failed"),
        poll=lambda: 2,
    )
    monkeypatch.setattr(ltx.subprocess, "Popen", lambda *args, **kwargs: process)
    with pytest.raises(Exception, match="LTX-2.5 generation failed") as exc:
        ltx._run(["python"], env={}, timeout_s=10, cancel_check=None)
    assert "CUDA allocation failed" in (exc.value.hint or "")


def test_decode_rejects_missing_or_empty_mp4(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="valid MP4"):
        ltx.decode_mp4(tmp_path / "missing.mp4")
    empty = tmp_path / "empty.mp4"
    empty.touch()
    with pytest.raises(Exception, match="valid MP4"):
        ltx.decode_mp4(empty)


def test_registry_exposes_real_ltx_smoke_callback() -> None:
    adapter = create_default_registry().adapter("hf_ltx_25_distilled_internal")
    assert adapter.descriptor.adapter_ready is True
    assert adapter.descriptor.smoke_test_supported is True
    assert adapter.descriptor.runtime_version == "ltx-pipelines==1.3.0"
    assert adapter.smoke_test is not None


def test_internal_video_dispatches_ltx_and_trims_legal_frame_count(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "model"
    root.mkdir()
    expected = [Image.new("RGB", (64, 64)) for _ in range(17)]
    captured = {}
    monkeypatch.setattr(ivm, "validate_video_model_layout", lambda *args: None)

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(ltx, "generate_ltx_frames", fake_generate)
    result = ivm.generate_video_model_frames(
        engine="ltx_25", video_model_dir=root, base_model_dir=root,
        init_image=None, prompt="test", negative_prompt="", width=64, height=64,
        num_frames=10, fps=8, steps=4, cfg=1, seed=5, device="cuda:0",
        workspace=tmp_path / "work", cancel_check=lambda: False,
    )
    assert result == expected[:10]
    assert captured["num_frames"] == 17
    assert captured["device"] == "cuda:0"
    assert captured["workspace"] == tmp_path / "work"
