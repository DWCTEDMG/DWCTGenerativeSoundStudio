"""Real opt-in Internal Renderer reference/accelerated/fallback image comparison."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_backend"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--size", type=int, default=128)
    args = parser.parse_args()
    args.data = args.data.resolve()
    args.data.mkdir(parents=True, exist_ok=True)
    os.environ["EDMG_STUDIO_DATA_DIR"] = str(args.data)
    from edmg_studio_backend.cuda_dll_path import prepare_cuda_dll_path
    prepare_cuda_dll_path()
    import numpy as np
    from edmg_studio_backend.services.internal_video import (
        InternalVideoSettings, release_cached_internal_pipelines, render_internal_still_image,
    )
    from edmg_studio_backend.services.render_settings import RenderSettingsStore
    store = RenderSettingsStore(args.data)
    settings = InternalVideoSettings(width=args.size, height=args.size, steps=4, cfg=5.0,
        seed=1234, device_preference="cuda", negative_prompt="")
    report = {}
    images = {}
    try:
        for label, policy in (
            ("reference", {"mode": "pytorch_cuda", "enabled": False, "package_path": ""}),
            ("accelerated", {"mode": "performance", "enabled": True, "auto_build": True, "package_path": ""}),
            ("missing_runtime_fallback", {"mode": "tensorrt", "enabled": True,
                                          "package_path": str(args.data / "absent-sdk")}),
        ):
            store.update({"runtime": policy})
            start = time.perf_counter()
            result = render_internal_still_image(model_dir=args.model.resolve(), settings=settings,
                workflow_family="txt2img", prompt="A single red ceramic teapot on a wooden table, studio photograph")
            image = result.pop("image")
            image.save(args.data / f"{label}.png")
            images[label] = np.asarray(image).astype(np.float32)
            report[label] = {**result, "total_seconds_including_load_or_build": time.perf_counter() - start}
            release_cached_internal_pipelines()
        if report["accelerated"]["runtime"].get("selected") != "tensorrt":
            raise RuntimeError("Internal Renderer did not use TensorRT: " + str(report["accelerated"]["runtime"]))
        if not np.array_equal(images["reference"], images["missing_runtime_fallback"]):
            raise RuntimeError("Missing-runtime fallback changed the deterministic reference image")
        report["mean_pixel_error"] = float(np.abs(images["reference"] - images["accelerated"]).mean())
        report["fallback_exact"] = True
        report["passed"] = report["mean_pixel_error"] < 2.0
        if not report["passed"]:
            raise RuntimeError("Accelerated image exceeded the pixel comparison tolerance")
    finally:
        release_cached_internal_pipelines()
        (args.data / "render-validation.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
