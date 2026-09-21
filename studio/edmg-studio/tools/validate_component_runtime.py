"""Opt-in real CUDA validation of cache reuse and native-worker death fallback.

Run with the existing backend interpreter; this never installs dependencies or downloads models.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_backend"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--size", type=int, default=128)
    parser.add_argument("--precision", choices=["fp32", "fp16"], default="fp32")
    args = parser.parse_args()
    from edmg_studio_backend.cuda_dll_path import prepare_cuda_dll_path
    prepare_cuda_dll_path()
    import torch
    from diffusers import AutoencoderKL
    from edmg_studio_backend.runtime.manager import RuntimeManager
    from edmg_studio_backend.runtime.policy import RuntimePolicy
    from edmg_studio_backend.runtime.process import RuntimeProcess
    args.data.mkdir(parents=True, exist_ok=True)
    dtype = torch.float16 if args.precision == "fp16" else torch.float32
    device = f"cuda:{args.device}"
    with RuntimeProcess(args.data) as child:
        prepared = child.request("prepare", timeout_s=1800, model_dir=str(args.model.resolve()),
            shape=[1, 4, args.size // 8, args.size // 8], precision=args.precision,
            device=args.device, allow_build=True)
    vae = AutoencoderKL.from_pretrained(str(args.model / "vae"), local_files_only=True,
        use_safetensors=True, torch_dtype=dtype).to(device).eval()
    manager = RuntimeManager(RuntimePolicy(mode="tensorrt", auto_build=False), args.data, args.model.resolve(), vae.decode)
    try:
        with torch.inference_mode():
            generator = torch.Generator(device=device).manual_seed(271828)
            latent = torch.randn((1, 4, args.size // 8, args.size // 8), device=device, dtype=dtype, generator=generator)
            reference = vae.decode(latent, return_dict=False)[0]
            accelerated = manager.decode(latent, return_dict=False)[0]
            if manager.plan.selected != "tensorrt":
                raise RuntimeError(f"Real component did not use TensorRT: {manager.plan.fallback_history}")
            max_error = (reference.float() - accelerated.float()).abs().max().item()
            if max_error > (0.05 if dtype == torch.float16 else 0.005):
                raise RuntimeError(f"Real validation error exceeded tolerance: {max_error}")
            accelerated_plan = asdict(manager.plan)
            # Deliberately kill only our disposable child, simulating a native crash.
            manager.process.process.kill()
            manager.process.process.wait(timeout=10)
            recovered = manager.decode(latent, return_dict=False)[0]
            if not torch.equal(recovered, reference) or manager.plan.selected != "pytorch_cuda":
                raise RuntimeError("Native worker death did not recover the exact PyTorch decode")
            report = {"passed": True, "accelerated_plan": accelerated_plan,
                "fallback_plan": asdict(manager.plan), "max_absolute_error": max_error,
                "exact_latent_fallback": True, "component_build": prepared}
            (args.data / "real-fallback-validation.json").write_text(json.dumps(report, indent=2))
            print(json.dumps(report, indent=2))
    finally:
        manager.cleanup()


if __name__ == "__main__":
    main()
