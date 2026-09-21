"""Resumable, sequential four-engine renders using Studio's existing adapters."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

STUDIO = Path(__file__).resolve().parents[1]
BACKEND = STUDIO / "python_backend"
PROJECT = STUDIO / "data/projects/8e6d6cc1148045949fff6405b07099e2"
AUDIO = PROJECT / "assets/audio/LANDR-The_End-Balanced-Low-REV_V3.wav"
DIRECTION = PROJECT / "outputs/qwen-abstract-preview/director-preview.json"
ANCHOR = PROJECT / "outputs/qwen-abstract-preview/ltx-native.mp4"
ROOT = PROJECT / "outputs/videos/the-end-comparison"
PYTHON = BACKEND / ".venv/Scripts/python.exe"
MODELS = STUDIO / "models/internal"
FPS, WIDTH, HEIGHT = 12, 512, 320
PREVIEW_DURATION = 4.0
ENGINES = {
    "hunyuan_video15": ("hf_hunyuan_video15_internal", 48, 8, 1.0, "Hunyuan"),
    "ltx_25": ("hf_ltx_25_distilled_internal", 48, 8, 1.0, "LTX"),
    "animatediff": ("hf_animatediff_motion_adapter_v15_2_internal", 16, 25, 6.0, "AnimateDiff"),
    "svd": ("hf_svd_xt_1_1_internal", 24, 25, 3.0, "SVD-XT"),
}
sys.path.insert(0, str(BACKEND))


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def configuration() -> None:
    for name in ("launcher_env.defaults.json", "launcher_env.json"):
        path = STUDIO / name
        if path.exists():
            for key, value in json.loads(path.read_text(encoding="utf-8")).items():
                if value is not None:
                    os.environ[key] = str(value)
    os.environ["EDMG_STUDIO_HOME"] = str(STUDIO)
    os.environ["EDMG_LTX25_PYTHON"] = str(STUDIO / "tools/ltx-2.5-env/Scripts/python.exe")
    os.environ["CUDA_VISIBLE_DEVICES"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["PYTHONUNBUFFERED"] = "1"


def preflight() -> dict:
    import soundfile as sf
    from edmg_studio_backend.services.internal_video_models import validate_video_model_layout
    from edmg_studio_backend.services.model_catalog import built_in_catalog
    from edmg_studio_backend.services.model_manager import ModelManager

    for path in (AUDIO, DIRECTION, ANCHOR, PYTHON, STUDIO / "tools/ltx-2.5-env/Scripts/python.exe"):
        if not path.is_file():
            raise FileNotFoundError(path)
    manager = object.__new__(ModelManager)
    catalog = {entry["id"]: entry for entry in built_in_catalog()}
    for engine, (model_id, *_rest) in ENGINES.items():
        validate_video_model_layout(engine, MODELS / "video" / model_id)
        if not manager._internal_asset_installed(catalog[model_id], MODELS / "video" / model_id):
            raise RuntimeError(f"Model is incomplete: {model_id}")
    if not manager._internal_asset_installed(catalog["hf_sd15_internal"], MODELS / "diffusers/hf_sd15_internal"):
        raise RuntimeError("AnimateDiff SD1.5 base is incomplete")
    info = sf.info(AUDIO)
    spec = {"schema": 1, "audio_sha256": hashlib.file_digest(AUDIO.open("rb"), "sha256").hexdigest(),
            "direction_sha256": hashlib.sha256(DIRECTION.read_bytes()).hexdigest(),
            "anchor_sha256": hashlib.file_digest(ANCHOR.open("rb"), "sha256").hexdigest(),
            "duration": info.frames / info.samplerate, "sample_rate": info.samplerate,
            "width": WIDTH, "height": HEIGHT, "native_fps": FPS, "output_fps": 24,
            "engines": ENGINES, "preview_duration": PREVIEW_DURATION, "gpu": 1, "seed": 241600}
    spec["fingerprint"] = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    return spec


def probe(path: Path) -> dict:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                            capture_output=True, text=True, check=True, timeout=30)
    return json.loads(result.stdout)


def valid_video(path: Path, frames: int, fps: int) -> bool:
    try:
        stream = next(s for s in probe(path)["streams"] if s["codec_type"] == "video")
        return (int(stream["nb_frames"]) == frames and stream["width"] == WIDTH
                and stream["height"] == HEIGHT and abs(float(stream["duration"]) - frames / fps) < 0.02)
    except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError):
        return False


def encode_frames(frames, path: Path) -> None:
    raw = b"".join(frame.convert("RGB").tobytes() for frame in frames)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pixel_format", "rgb24",
                    "-video_size", f"{WIDTH}x{HEIGHT}", "-framerate", str(FPS), "-i", "pipe:0",
                    "-an", "-c:v", "libx264", "-crf", "17", "-preset", "fast", "-pix_fmt", "yuv420p", str(path)],
                   input=raw, check=True, timeout=180)


def worker(engine: str, stage: str, spec: dict) -> None:
    import cv2
    import numpy as np
    import soundfile as sf
    from PIL import Image
    from edmg_studio_backend.services.internal_video_models import generate_video_model_frames
    from edmg_studio_backend.services.video_motion_quality import analyze_motion_images

    model_id, per_clip, steps, cfg, label = ENGINES[engine]
    lane = ROOT / engine
    clips = lane / "segments"
    clips.mkdir(parents=True, exist_ok=True)
    target_duration = min(PREVIEW_DURATION, spec["duration"]) if stage == "preview" else spec["duration"]
    count = math.ceil(target_duration * FPS / per_clip)
    direction = json.loads(DIRECTION.read_text(encoding="utf-8"))
    # Existing Qwen actions provide the visual vocabulary; timing comes from this audio.
    actions = " ".join(direction["document"]["scenes"][0]["actions"])
    base_prompt = ("Abstract sculptural liquid-metal ribbons and translucent faceted geometry, cyan crimson silver, "
                   "black spatial field, smooth continuous transformation, cinematic depth, no people or lettering. " + actions)
    audio, sample_rate = sf.read(AUDIO, dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    hop = sample_rate // FPS
    rms = np.array([np.sqrt(np.mean(mono[i:i + hop] ** 2)) for i in range(0, len(mono), hop)])
    rms /= max(float(np.percentile(rms, 95)), 1e-6)
    rms = np.clip(rms, 0, 1)
    for index in range(1, len(rms)):
        rms[index] = 0.6 * rms[index - 1] + 0.4 * rms[index]
    anchors = []
    if engine == "svd":
        capture = cv2.VideoCapture(str(ANCHOR))
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            anchors.append(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        capture.release()
        if not anchors:
            raise RuntimeError("SVD image anchors could not be decoded")
    for index in range(count):
        clip = clips / f"{index:04d}.mp4"
        receipt = clip.with_suffix(".json")
        seed = 241600 + index
        if receipt.exists() and clip.exists():
            old = json.loads(receipt.read_text(encoding="utf-8"))
            if old.get("fingerprint") == spec["fingerprint"] and valid_video(clip, per_clip, FPS):
                print(f"{engine}: reuse segment {index + 1}/{count}", flush=True)
                continue
        start_s = index * per_clip / FPS
        start = min(int(start_s * sample_rate), len(mono) - 1)
        end = min(start + int(per_clip / FPS * sample_rate), len(mono))
        window = mono[start:end]
        spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window)))) ** 2
        frequencies = np.fft.rfftfreq(len(window), 1 / sample_rate)
        bands = [float(spectrum[(frequencies >= low) & (frequencies < high)].sum())
                 for low, high in ((20, 250), (250, 4000), (4000, 16000))]
        dominant = ("broad flowing expansion", "layered twisting ribbons", "fine crystalline edge motion")[int(np.argmax(bands))]
        phase = min(5, int(start_s / spec["duration"] * 6))
        motifs = ("folded silver petals", "interlocking translucent fins", "flowing metallic loops",
                  "expanding glass lattice", "braided crimson and cyan ribbons", "dissolving silver folds")
        prompt = f"{base_prompt} This shot evolves {motifs[phase]}; emphasize {dominant}. Smooth dolly, no flashing."
        if engine == "animatediff":
            prompt = f"abstract {motifs[phase]}, sculptural liquid metal, translucent faceted geometry, cyan crimson silver on black, {dominant}, cinematic depth, smooth motion"
        state = {"engine": engine, "stage": stage, "status": "rendering", "segment": index + 1,
                 "segments": count, "start_s": start_s, "updated_at": time.time()}
        save(lane / "progress.json", state)
        print(json.dumps(state), flush=True)
        evidence = None
        for attempt in range(2):
            init_image = anchors[min(len(anchors) - 1, int((index * 0.61803398875 % 1) * len(anchors)))] if anchors else None
            requested_frames = per_clip + 1 if engine != "animatediff" else per_clip
            frames = generate_video_model_frames(
                engine=engine, video_model_dir=MODELS / "video" / model_id,
                base_model_dir=MODELS / "diffusers/hf_sd15_internal", init_image=init_image,
                prompt=prompt, negative_prompt="text, logos, watermark, people, low quality, flicker, static image",
                width=WIDTH, height=HEIGHT, num_frames=requested_frames, fps=FPS,
                steps=steps, cfg=cfg, seed=seed + attempt * 100000,
                device="cuda:1" if engine in {"hunyuan_video15", "ltx_25"} else "cuda",
                dtype="bfloat16" if engine in {"hunyuan_video15", "ltx_25"} else "float16",
                cpu_offload=engine in {"hunyuan_video15", "ltx_25"}, decode_chunk_size=4,
                workspace=lane, generation_mode="t2v", chunk_frames=requested_frames,
            )
            frames = frames[:per_clip]
            evidence = analyze_motion_images(frames, fps=FPS)
            if evidence["status"] == "pass":
                break
        if evidence["status"] != "pass":
            raise RuntimeError(f"{engine} segment {index} failed native motion validation: {evidence}")
        for offset, frame in enumerate(frames):
            level = float(rms[min(index * per_clip + offset, len(rms) - 1)])
            pixels = np.asarray(frame.convert("RGB"))
            matrix = cv2.getRotationMatrix2D((WIDTH / 2, HEIGHT / 2), 0, 1 + 0.025 * level)
            pixels = cv2.warpAffine(pixels, matrix, (WIDTH, HEIGHT), borderMode=cv2.BORDER_REFLECT)
            pixels = np.clip(pixels.astype(np.float32) * (0.94 + 0.12 * level), 0, 255).astype(np.uint8)
            frames[offset] = Image.fromarray(pixels)
        temporary = clip.with_name(clip.stem + ".partial.mp4")
        encode_frames(frames, temporary)
        if not valid_video(temporary, per_clip, FPS):
            raise RuntimeError("Encoded segment failed validation")
        os.replace(temporary, clip)
        save(receipt, {"fingerprint": spec["fingerprint"], "seed": seed + attempt * 100000,
                       "prompt": prompt, "native_motion": evidence, "start_s": start_s,
                       "frames": per_clip, "source": model_id})
    concat = lane / f"{stage}-concat.txt"
    concat.write_text("".join(f"file 'segments/{index:04d}.mp4'\n" for index in range(count)), encoding="ascii")
    output = lane / f"The-End-{label}-{stage}.mp4"
    temporary = output.with_name(output.stem + ".partial.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
                    "-i", str(AUDIO), "-map", "0:v:0", "-map", "1:a:0", "-t", str(target_duration),
                    "-vf", "minterpolate=fps=24:mi_mode=mci,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=1,fps=24",
                    "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(temporary)],
                   check=True, timeout=1800)
    info = probe(temporary)
    for kind in ("video", "audio"):
        stream = next(item for item in info["streams"] if item["codec_type"] == kind)
        if abs(float(stream["duration"]) - target_duration) > 1 / 24 + 0.01:
            raise RuntimeError(f"Final {kind} duration mismatch: {stream['duration']}")
    os.replace(temporary, output)
    cap = cv2.VideoCapture(str(output))
    samples = []
    for position in (0.1, 0.35, 0.65, 0.9):
        cap.set(cv2.CAP_PROP_POS_MSEC, position * target_duration * 1000)
        ok, frame = cap.read()
        if not ok or float(frame.std()) < 2:
            raise RuntimeError("Output is blank or could not be decoded")
        samples.append(frame)
    cap.release()
    cv2.imwrite(str(lane / f"{stage}-contact-sheet.jpg"), np.vstack((np.hstack(samples[:2]), np.hstack(samples[2:]))))
    save(output.with_suffix(".receipt.json"), {"fingerprint": spec["fingerprint"], "engine": engine,
         "stage": stage, "status": "complete", "duration": target_duration, "segments": count,
         "output": str(output), "director": direction["provenance"], "ffprobe": info,
         "audio_modulation": "Smoothed source RMS controls gentle zoom and brightness"})
    save(lane / "progress.json", {"engine": engine, "stage": stage, "status": "complete", "output": str(output)})
    print(f"COMPLETE {engine} {stage}: {output}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--engine", choices=ENGINES)
    parser.add_argument("--stage", choices=("preview", "full"))
    args = parser.parse_args()
    configuration()
    spec = preflight()
    if args.check:
        print(json.dumps(spec, indent=2))
        return 0
    if args.engine:
        if not args.stage:
            parser.error("--engine requires --stage")
        try:
            worker(args.engine, args.stage, spec)
        except Exception as exc:
            save(ROOT / args.engine / "progress.json", {
                "engine": args.engine,
                "stage": args.stage,
                "status": "failed",
                "error": str(exc),
                "updated_at": time.time(),
            })
            raise
        return 0
    from filelock import FileLock
    ROOT.mkdir(parents=True, exist_ok=True)
    with FileLock(str(ROOT / "batch.lock"), timeout=0):
        manifest = ROOT / "batch.json"
        if manifest.exists():
            old = json.loads(manifest.read_text(encoding="utf-8"))
            if old["spec"]["fingerprint"] != spec["fingerprint"]:
                raise RuntimeError("Existing batch has different inputs; use a new output folder")
        state = {"spec": spec, "status": "running", "results": {}, "started_at": time.time()}
        save(manifest, state)
        ready = []
        for stage in ("preview", "full"):
            for engine in (ENGINES if stage == "preview" else ready.copy()):
                key = f"{engine}:{stage}"
                state["current"] = key
                save(manifest, state)
                log_path = ROOT / f"{engine}-{stage}.log"
                print(f"START {key}", flush=True)
                with log_path.open("a", encoding="utf-8") as log:
                    result = subprocess.run([str(PYTHON), "-u", str(Path(__file__).resolve()),
                                             "--engine", engine, "--stage", stage],
                                            stdout=log, stderr=subprocess.STDOUT, cwd=STUDIO)
                if result.returncode == 0:
                    state["results"][key] = {"status": "complete", "log": str(log_path)}
                    if stage == "preview":
                        ready.append(engine)
                else:
                    state["results"][key] = {"status": "failed", "exit_code": result.returncode,
                                             "log": str(log_path), "error": log_path.read_text(encoding="utf-8")[-5000:]}
                    if stage == "preview":
                        state["results"][f"{engine}:full"] = {"status": "blocked", "reason": "Preview failed; see preview log"}
                save(manifest, state)
                print(f"{state['results'][key]['status'].upper()} {key}", flush=True)
        failed = any(item["status"] != "complete" for item in state["results"].values())
        state.update(status="finished_with_errors" if failed else "complete", ended_at=time.time(), current=None)
        save(manifest, state)
        print(json.dumps(state, indent=2), flush=True)
        return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
