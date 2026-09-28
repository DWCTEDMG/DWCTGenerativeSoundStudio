"""Exercise the Studio TorchScript -> Torch-TensorRT route through its isolated worker."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import numpy as np
import torch

from edmg_studio_backend.runtime.process import RuntimeProcess


class TinyUnet(torch.nn.Module):
    def forward(self, sample, timestep, encoder_hidden_states):
        scale = timestep.reshape(-1, 1, 1, 1) / 1000.0
        conditioning = encoder_hidden_states.mean(dim=(1, 2)).reshape(-1, 1, 1, 1)
        return sample * scale + conditioning


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for Torch-TensorRT route validation")

    # Native compiler helpers may release inherited Windows handles asynchronously after a
    # failed build.  Preserve the actual compiler error instead of masking it with cleanup.
    with tempfile.TemporaryDirectory(
        prefix="edmg-torchtrt-route-", ignore_cleanup_errors=True
    ) as temporary:
        root = Path(temporary)
        model_dir = root / "model"
        model_dir.mkdir()
        sample = torch.zeros((1, 4, 8, 8))
        timestep = torch.tensor([500.0])
        hidden = torch.zeros((1, 77, 768))
        traced = torch.jit.trace(TinyUnet().eval(), (sample, timestep, hidden))
        traced.save(str(model_dir / "tiny-unet.pt"))

        data_dir = (args.data_dir or (root / "data")).resolve()
        with RuntimeProcess(data_dir) as process:
            prepared = process.request(
                "prepare", timeout_s=900, model_dir=str(model_dir),
                shape=list(sample.shape), precision="fp32", device=args.device,
                model_family="sd15", component="unet", allow_build=True,
            )
            executed = process.request(
                "execute", timeout_s=180,
                arrays={
                    "sample": sample.numpy(),
                    "timestep": timestep.numpy(),
                    "encoder_hidden_states": hidden.numpy(),
                },
            )
        with RuntimeProcess(data_dir) as process:
            cached = process.request(
                "prepare", timeout_s=180, model_dir=str(model_dir),
                shape=list(sample.shape), precision="fp32", device=args.device,
                model_family="sd15", component="unet", allow_build=False,
            )
            cached_execution = process.request(
                "execute", timeout_s=180,
                arrays={
                    "sample": sample.numpy(),
                    "timestep": timestep.numpy(),
                    "encoder_hidden_states": hidden.numpy(),
                },
            )
        output = executed["output"]
        expected = sample.numpy() * 0.5
        if output.shape != expected.shape or not np.allclose(output, expected, rtol=0.005, atol=0.005):
            raise RuntimeError("Compiled worker output did not match the PyTorch reference")
        if cached["cache"] != "ready" or not np.allclose(
            cached_execution["output"], expected, rtol=0.005, atol=0.005
        ):
            raise RuntimeError("Validated Torch-TensorRT cache could not be reused without rebuilding")
        receipt = {
            "ok": True,
            "source_kind": prepared["source_kind"],
            "selected_route": prepared["selected_route"],
            "compiler": prepared["compiler"],
            "cache": prepared["cache"],
            "cache_reuse": cached["cache"],
            "engine_id": prepared["manifest"]["engine_id"],
            "validation": prepared["manifest"]["validation"],
            "inference_s": executed["inference_s"],
            "output_shape": list(output.shape),
        }
        print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
