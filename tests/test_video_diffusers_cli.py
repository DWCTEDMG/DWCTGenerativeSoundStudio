from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_script_module(script_path: Path):
    name = "video_diffusers_cli_test"
    spec = importlib.util.spec_from_file_location(name, script_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def test_run_svd_pipeline_falls_back_when_guidance_scale_is_unsupported() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (
        repo_root
        / "studio"
        / "edmg-studio"
        / "python_backend"
        / "enhanced_deforum_music_generator"
        / "cli"
        / "video_diffusers.py"
    )
    mod = _load_script_module(script)
    calls: list[dict[str, object]] = []

    class FakePipe:
        def __call__(self, **kwargs):
            calls.append(dict(kwargs))
            if "guidance_scale" in kwargs:
                raise TypeError("StableVideoDiffusionPipeline.__call__() got an unexpected keyword argument 'guidance_scale'")
            return type("Result", (), {"frames": [["frame-1", "frame-2"]]})()

    result = mod._run_svd_pipeline(
        FakePipe(),
        image="image",
        num_frames=4,
        steps=2,
        guidance_scale=1.5,
        generator="generator",
    )

    assert len(calls) == 2
    assert "guidance_scale" in calls[0]
    assert "guidance_scale" not in calls[1]
    assert result.frames[0] == ["frame-1", "frame-2"]
