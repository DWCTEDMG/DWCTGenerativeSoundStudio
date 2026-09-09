"""Linux-only isolated worker for the official HunyuanVideo-1.5 pipeline."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


def _link(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(source, target_is_directory=source.is_dir())


def _overlay(args: argparse.Namespace, root: Path) -> None:
    model = Path(args.model)
    for name in ("config.json", "scheduler", "vae", "transformer"):
        source = model / name
        _link(source, root / name)
    _link(Path(args.llm), root / "text_encoder" / "llm")
    _link(Path(args.byt5), root / "text_encoder" / "byt5-small")
    _link(Path(args.glyph), root / "text_encoder" / "Glyph-SDXL-v2")
    _link(Path(args.vision), root / "vision_encoder" / "siglip")


def _save_video(video, output: Path, fps: int) -> None:
    import einops
    import imageio
    import torch

    if video.ndim == 5:
        if video.shape[0] != 1:
            raise RuntimeError(f"Expected one generated video, got batch size {video.shape[0]}")
        video = video[0]
    frames = (video * 255).clamp(0, 255).to(torch.uint8)
    frames = einops.rearrange(frames, "c f h w -> f h w c").cpu().numpy()
    output.parent.mkdir(parents=True, exist_ok=True)
    imageio.mimwrite(str(output), frames, fps=fps)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--llm", required=True)
    parser.add_argument("--byt5", required=True)
    parser.add_argument("--glyph", required=True)
    parser.add_argument("--vision", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--pid-file", required=True)
    args = parser.parse_args()
    Path(args.pid_file).write_text(str(os.getpid()), encoding="ascii")
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))

    import torch
    from hyvideo.commons.infer_state import InferState
    from hyvideo.pipelines.hunyuan_video_pipeline import HunyuanVideo_1_5_Pipeline

    dtype = {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}[request["dtype"]]
    task = request["mode"]
    transformer_version = HunyuanVideo_1_5_Pipeline.get_transformer_version(
        request["resolution"], task, request["cfg_distilled"], request["step_distilled"], False
    )
    with tempfile.TemporaryDirectory(prefix="edmg-hunyuan-") as temporary:
        overlay = Path(temporary)
        _overlay(args, overlay)
        offload = bool(request["cpu_offload"])
        device = torch.device("cpu" if offload else "cuda:0")
        init_device = torch.device("cpu" if offload else "cuda:0")
        pipe = HunyuanVideo_1_5_Pipeline.create_pipeline(
            pretrained_model_name_or_path=str(overlay),
            transformer_version=transformer_version,
            create_sr_pipeline=False,
            transformer_dtype=dtype,
            device=device,
            transformer_init_device=init_device,
        )
        pipe.apply_infer_optimization(
            infer_state=InferState(total_steps=int(request["steps"])),
            enable_offloading=offload,
            enable_group_offloading=offload,
            overlap_group_offloading=False,
        )
        kwargs = {
            "prompt": request["prompt"],
            "negative_prompt": request["negative_prompt"],
            "aspect_ratio": f'{request["width"]}:{request["height"]}',
            "video_length": int(request["frames"]),
            "num_inference_steps": int(request["steps"]),
            "guidance_scale": float(request["guidance_scale"]),
            "seed": int(request["seed"]),
            "prompt_rewrite": False,
            "enable_sr": False,
            "output_type": "pt",
        }
        if request.get("image"):
            kwargs["reference_image"] = request["image"]
        result = pipe(**kwargs)
        video = getattr(result, "videos", None)
        if video is None:
            raise RuntimeError("Official Hunyuan pipeline returned no video tensor")
        _save_video(video, Path(args.output), int(request["fps"]))


if __name__ == "__main__":
    main()
