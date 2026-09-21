"""Linux-only isolated worker for the official HunyuanVideo-1.5 pipeline."""
from __future__ import annotations

import argparse
from datetime import timedelta
import json
import os
import sys
import tempfile
import time
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


def _memory_status(stage: str, rank: int) -> None:
    import resource

    available_kib = "unknown"
    swap_free_kib = "unknown"
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            key, value = line.split(":", 1)
            values[key] = value.strip().split()[0]
        available_kib = values.get("MemAvailable", available_kib)
        swap_free_kib = values.get("SwapFree", swap_free_kib)
    except (OSError, ValueError):
        pass
    peak_rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(
        f"[edmg-memory] time={time.time():.3f} rank={rank} stage={stage} "
        f"peak_rss_kib={peak_rss_kib} available_kib={available_kib} swap_free_kib={swap_free_kib}",
        file=sys.stderr,
        flush=True,
    )


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
    import torch.distributed as dist
    from hyvideo.commons.infer_state import InferState
    from hyvideo.commons.parallel_states import initialize_parallel_state
    from hyvideo.pipelines.hunyuan_video_pipeline import HunyuanVideo_1_5_Pipeline

    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    torch.cuda.set_device(local_rank)
    load_group_initialized = False
    if world_size > 1 and not dist.is_initialized():
        dist.init_process_group(backend="gloo", timeout=timedelta(hours=2))
        load_group_initialized = True

    dtype = {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}[request["dtype"]]
    task = request["mode"]
    transformer_version = HunyuanVideo_1_5_Pipeline.get_transformer_version(
        request["resolution"], task, request["cfg_distilled"], request["step_distilled"], False
    )
    with tempfile.TemporaryDirectory(prefix="edmg-hunyuan-") as temporary:
        overlay = Path(temporary)
        _overlay(args, overlay)
        offload = bool(request["cpu_offload"])
        device = torch.device("cpu" if offload else f"cuda:{local_rank}")
        init_device = torch.device("cpu" if offload else f"cuda:{local_rank}")
        pipe = None
        for load_rank in range(world_size):
            if local_rank == load_rank:
                _memory_status("pipeline_load_start", local_rank)
                pipe = HunyuanVideo_1_5_Pipeline.create_pipeline(
                    pretrained_model_name_or_path=str(overlay),
                    transformer_version=transformer_version,
                    create_sr_pipeline=False,
                    transformer_dtype=dtype,
                    device=device,
                    transformer_init_device=init_device,
                )
                _memory_status("pipeline_load_complete", local_rank)
            if world_size > 1:
                dist.barrier()
        if pipe is None:
            raise RuntimeError(f"Pipeline was not loaded for local rank {local_rank}")
        if load_group_initialized:
            dist.destroy_process_group()
            dist.init_process_group(backend="nccl", timeout=timedelta(hours=2))
        initialize_parallel_state(sp=world_size)
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
            "enable_vae_tile_parallelism": world_size > 1,
            "output_type": "pt",
        }
        if request.get("image"):
            kwargs["reference_image"] = request["image"]
        try:
            result = pipe(**kwargs)
            video = getattr(result, "videos", None)
            if video is None:
                raise RuntimeError("Official Hunyuan pipeline returned no video tensor")
            if world_size == 1 or dist.get_rank() == 0:
                _save_video(video, Path(args.output), int(request["fps"]))
            if world_size > 1:
                dist.barrier()
        finally:
            if torch.distributed.is_initialized():
                torch.distributed.destroy_process_group()


if __name__ == "__main__":
    main()
