"""Compile and execute the installed production SD1.5 component through Studio."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from edmg_studio_backend.runtime.process import RuntimeProcess
from edmg_studio_backend.runtime.policy import RuntimePolicy


def _inputs(component: str, shape: list[int]) -> dict[str, np.ndarray]:
    if component == "vae_decoder":
        return {"latent": np.zeros(shape, dtype=np.float16)}
    return {
        "sample": np.zeros(shape, dtype=np.float16),
        "timestep": np.array([500.0], dtype=np.float16),
        "encoder_hidden_states": np.zeros((shape[0], 77, 768), dtype=np.float16),
    }


def _output(result: dict) -> np.ndarray:
    if "output" in result:
        return result["output"]
    return next(iter(result.get("outputs", {}).values()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--component", choices=("vae_decoder", "unet"), required=True)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--latent-size", type=int, default=64)
    args = parser.parse_args()
    model_dir = args.model_dir.resolve()
    data_dir = args.data_dir.resolve()
    shape = [1, 4, args.latent_size, args.latent_size]
    values = _inputs(args.component, shape)
    validation_limits = RuntimePolicy().validation_limits("fp16", args.component)

    with RuntimeProcess(data_dir) as process:
        prepared = process.request(
            "prepare", timeout_s=3600, model_dir=str(model_dir), shape=shape,
            precision="fp16", device=args.device, model_family="sd15",
            component=args.component, allow_build=True,
            validation_limits=validation_limits,
        )
        executed = process.request("execute", timeout_s=600, arrays=values)

    with RuntimeProcess(data_dir) as process:
        cached = process.request(
            "prepare", timeout_s=600, model_dir=str(model_dir), shape=shape,
            precision="fp16", device=args.device, model_family="sd15",
            component=args.component, allow_build=False,
            validation_limits=validation_limits,
        )
        cached_execution = process.request("execute", timeout_s=600, arrays=values)

    output = _output(executed)
    cached_output = _output(cached_execution)
    if not np.isfinite(output).all() or not np.allclose(output, cached_output, rtol=0.03, atol=0.03):
        raise RuntimeError("Production TensorRT output or cache reload validation failed")
    print(json.dumps({
        "ok": True,
        "component": args.component,
        "model_dir": str(model_dir),
        "source_kind": prepared["source_kind"],
        "selected_route": prepared["selected_route"],
        "compiler": prepared["compiler"],
        "cache": prepared["cache"],
        "cache_reuse": cached["cache"],
        "engine_id": prepared["manifest"]["engine_id"],
        "compiled_format": prepared["manifest"].get("compiled_format"),
        "validation": prepared["manifest"]["validation"],
        "inference_s": executed["inference_s"],
        "output_shape": list(output.shape),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
