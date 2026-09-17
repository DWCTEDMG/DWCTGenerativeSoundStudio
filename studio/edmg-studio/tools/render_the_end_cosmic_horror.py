"""Resumable LTX-2.5 and HunyuanVideo-1.5 render of The End.

Each engine creates deterministic four-second shots. The first shot establishes the
traveler and town; every later shot is image-conditioned on the final accepted frame
from the preceding shot to preserve visual continuity.
"""
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
ROOT = PROJECT / "outputs/videos/the-end-cosmic-horror"
PYTHON = BACKEND / ".venv/Scripts/python.exe"
MODELS = STUDIO / "models/internal"
FPS = 12
OUTPUT_FPS = 24
WIDTH = 512
HEIGHT = 320
FRAMES_PER_SHOT = 48
SCHEMA = 2
BASE_SEED = 528031

ENGINES = {
    "ltx_25": {
        "model_id": "hf_ltx_25_distilled_internal",
        "steps": 8,
        "cfg": 1.0,
        "gpu": 2,
        "label": "LTX-2.5",
    },
    "hunyuan_video15": {
        "model_id": "hf_hunyuan_video15_internal",
        "steps": 30,
        "cfg": 1.0,
        "gpu": 0,
        "label": "HunyuanVideo-1.5",
    },
}

CHARACTER = (
    "The same androgynous adult traveler in every shot: ambiguous gender, slender average-height build, "
    "medium-length dark unkempt hair, long weathered charcoal-black coat, plain dark trousers, worn black "
    "boots, anonymous face usually hidden in shadow. Preserve exact identity, silhouette, wardrobe, hair, "
    "body proportions and direction of travel."
)
WORLD = (
    "One continuous journey deeper into the same isolated old rural town at night, damp cobblestones, "
    "weathered timber and stone buildings, sparse amber lantern light, cold moonlit fog, dark surrounding "
    "forest. Preserve spatial, architectural, lighting and weather continuity. Cinematic realistic texture, "
    "restrained desaturated charcoal, moon-blue and dim amber palette, deep focus, 24mm anamorphic character."
)
NEGATIVE = (
    "gore, blood, injury, attack, explicit monster, visible creature, jump scare, frantic action, running, "
    "shaky camera, handheld jitter, whip pan, rapid cut, strobe, bright daylight, cheerful mood, comedy, "
    "modern city, cars, weapons, dialogue, subtitles, text, title card, logo, watermark, duplicate protagonist, "
    "changing clothes, changing hair, changing identity, deformed body, extra limbs, close clear face, "
    "premature extreme surrealism, abrupt scene change, low quality, flicker, frozen frame"
)
CAMERAS = (
    "slow rear-follow tracking at walking pace with restrained foreground parallax",
    "slow lateral tracking through fence posts and bare branches with deliberate movement",
    "restrained dolly forward behind the traveler, stable horizon and patient composition",
    "slow three-quarter rear tracking, distant architecture held in deep focus",
    "gradual low crane movement revealing more of the road without breaking continuity",
)
ACTS = (
    (0.00, 0.12, "Grounded arrival", "The traveler enters the believable sleeping town alone. Ordinary dark windows, wet road and still trees; nothing overtly impossible."),
    (0.12, 0.24, "Lantern pattern", "Lanterns farther down the road ignite in an unnaturally synchronized sequence. Shadows are only subtly too long and point at slightly inconsistent angles."),
    (0.24, 0.36, "Incorrect facades", "Windows repeat at almost-correct intervals, rooflines bend by a few degrees, and distant silent human silhouettes watch from doorways without moving."),
    (0.36, 0.48, "Delayed reflections", "Shop glass and puddles reflect the traveler a moment late. A narrow alley appears deeper than the block can contain while the watchers remain distant."),
    (0.48, 0.60, "Faceless witnesses", "The watchers are now smooth featureless faceless residents in old dark rural clothes. They only watch; no one approaches or threatens the traveler."),
    (0.60, 0.72, "Silent procession", "Faceless residents slowly form a silent procession behind the traveler at a respectful distance, all moving with measured synchronized steps toward the central square."),
    (0.72, 0.84, "Conflicting town", "Interiors visible through windows are larger than their buildings, alleys descend impossibly far, reflections show altered streets, and perspective conflicts grow gradually."),
    (0.84, 0.93, "Obelisk approach", "The road opens toward the central square. An ancient weathered black-stone obelisk emerges through fog, surrounded by hundreds of motionless faceless residents."),
    (0.93, 0.975, "At the obelisk", "The traveler reaches the obelisk and stops walking for the first time. Reflections and shadows imply an enormous unknowable cosmic reality without revealing any being."),
    (0.975, 1.001, "Final retreat", "The camera slowly retreats. Streets, buildings and forest subtly curve inward and contradict perspective; residents remain motionless; the traveler is a small silhouette beside the obelisk while the traveler's shadow moves independently. Hold the disturbing composition."),
)

sys.path.insert(0, str(BACKEND))


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def sha256_image(image) -> str:
    return hashlib.sha256(image.convert("RGB").tobytes()).hexdigest()


def configure_environment() -> None:
    for name in ("launcher_env.defaults.json", "launcher_env.json"):
        path = STUDIO / name
        if path.exists():
            for key, value in json.loads(path.read_text(encoding="utf-8")).items():
                if value is not None:
                    os.environ[key] = str(value)
    os.environ["EDMG_STUDIO_HOME"] = str(STUDIO)
    os.environ["EDMG_LTX25_PYTHON"] = str(STUDIO / "tools/ltx-2.5-env/Scripts/python.exe")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["PYTHONUNBUFFERED"] = "1"


def preflight(engine: str) -> dict:
    import soundfile as sf
    from edmg_studio_backend.services.internal_video_models import validate_video_model_layout
    from edmg_studio_backend.services.model_catalog import built_in_catalog
    from edmg_studio_backend.services.model_manager import ModelManager

    config = ENGINES[engine]
    for path in (AUDIO, PYTHON):
        if not path.is_file():
            raise FileNotFoundError(path)
    model_dir = MODELS / "video" / config["model_id"]
    validate_video_model_layout(engine, model_dir)
    catalog = {entry["id"]: entry for entry in built_in_catalog()}
    manager = object.__new__(ModelManager)
    if not manager._internal_asset_installed(catalog[config["model_id"]], model_dir):
        raise RuntimeError(f"Model is incomplete: {config['model_id']}")
    runtime = {"admission": "direct_execution", "probe_required": False}
    info = sf.info(AUDIO)
    duration = info.frames / info.samplerate
    treatment = {"character": CHARACTER, "world": WORLD, "negative": NEGATIVE, "acts": ACTS}
    spec = {
        "schema": SCHEMA,
        "audio_sha256": sha256_file(AUDIO),
        "duration": duration,
        "sample_rate": info.samplerate,
        "audio_frames": info.frames,
        "width": WIDTH,
        "height": HEIGHT,
        "native_fps": FPS,
        "output_fps": OUTPUT_FPS,
        "frames_per_shot": FRAMES_PER_SHOT,
        "engine": engine,
        "engine_config": config,
        "seed": BASE_SEED,
        "treatment": treatment,
        "runtime": runtime,
    }
    fingerprint_value = dict(spec)
    fingerprint_value.pop("runtime")
    spec["fingerprint"] = hashlib.sha256(
        json.dumps(fingerprint_value, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return spec


def probe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(result.stdout)


def valid_segment(path: Path) -> bool:
    try:
        stream = next(item for item in probe(path)["streams"] if item["codec_type"] == "video")
        return (
            int(stream["nb_frames"]) == FRAMES_PER_SHOT
            and int(stream["width"]) == WIDTH
            and int(stream["height"]) == HEIGHT
            and abs(float(stream["duration"]) - FRAMES_PER_SHOT / FPS) < 0.02
        )
    except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError):
        return False


def last_frame(path: Path):
    import cv2
    from PIL import Image

    capture = cv2.VideoCapture(str(path))
    frame = None
    try:
        while True:
            ok, candidate = capture.read()
            if not ok:
                break
            frame = candidate
    finally:
        capture.release()
    if frame is None:
        raise RuntimeError(f"Could not decode continuity frame from {path}")
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


def encode_frames(frames, path: Path) -> None:
    raw = b"".join(frame.convert("RGB").tobytes() for frame in frames)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pixel_format", "rgb24",
            "-video_size", f"{WIDTH}x{HEIGHT}", "-framerate", str(FPS), "-i", "pipe:0",
            "-an", "-c:v", "libx264", "-crf", "17", "-preset", "fast", "-pix_fmt", "yuv420p", str(path),
        ],
        input=raw,
        check=True,
        timeout=300,
    )


def act_for(progress: float) -> tuple[int, str, str]:
    for index, (start, end, name, action) in enumerate(ACTS):
        if start <= progress < end:
            return index, name, action
    return len(ACTS) - 1, ACTS[-1][2], ACTS[-1][3]


def shot_prompt(index: int, count: int, dominant: str) -> tuple[str, str, str]:
    progress = min(index / max(count - 1, 1), 1.0)
    act_index, act_name, action = act_for(progress)
    camera = CAMERAS[(index + act_index) % len(CAMERAS)]
    continuity = (
        "Continue directly from the supplied previous frame with no cut, location reset, wardrobe change or identity drift."
        if index else
        "Establish the traveler from behind at the town boundary in a grounded, believable opening composition."
    )
    prompt = (
        f"{CHARACTER} {WORLD} {continuity} Act: {act_name}. {action} "
        f"Shot language: {camera}. The source music suggests {dominant}; express it only through restrained fog drift, "
        "lantern breathing, shadow movement and camera pace. Slow-burn cosmic horror, deliberate cinematic movement, "
        "natural escalation from the immediately preceding shot."
    )
    return prompt, act_name, camera


def audio_features(spec: dict):
    import numpy as np
    import soundfile as sf

    audio, sample_rate = sf.read(AUDIO, dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    hop = sample_rate // FPS
    rms = np.array([
        np.sqrt(np.mean(mono[start:start + hop] ** 2))
        for start in range(0, len(mono), hop)
    ])
    rms /= max(float(np.percentile(rms, 95)), 1e-6)
    rms = np.clip(rms, 0, 1)
    for index in range(1, len(rms)):
        rms[index] = 0.75 * rms[index - 1] + 0.25 * rms[index]
    return mono, sample_rate, rms


def dominant_motion(mono, sample_rate: int, start_s: float) -> str:
    import numpy as np

    start = min(int(start_s * sample_rate), len(mono) - 1)
    end = min(start + int(FRAMES_PER_SHOT / FPS * sample_rate), len(mono))
    window = mono[start:end]
    spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window)))) ** 2
    frequencies = np.fft.rfftfreq(len(window), 1 / sample_rate)
    bands = [
        float(spectrum[(frequencies >= low) & (frequencies < high)].sum())
        for low, high in ((20, 250), (250, 4000), (4000, 16000))
    ]
    return (
        "weighty low-frequency forward drift",
        "measured midrange architectural parallax",
        "fine high-frequency fog and lantern shimmer",
    )[int(np.argmax(bands))]


def apply_audio_modulation(frames, rms, frame_offset: int):
    import cv2
    import numpy as np
    from PIL import Image

    result = []
    for offset, frame in enumerate(frames):
        level = float(rms[min(frame_offset + offset, len(rms) - 1)])
        pixels = np.asarray(frame.convert("RGB"))
        matrix = cv2.getRotationMatrix2D((WIDTH / 2, HEIGHT / 2), 0, 1 + 0.009 * level)
        pixels = cv2.warpAffine(pixels, matrix, (WIDTH, HEIGHT), borderMode=cv2.BORDER_REFLECT)
        pixels = np.clip(pixels.astype(np.float32) * (0.975 + 0.04 * level), 0, 255).astype(np.uint8)
        result.append(Image.fromarray(pixels))
    return result


def render(engine: str, smoke: bool, spec: dict) -> Path | None:
    import cv2
    import numpy as np
    from filelock import FileLock
    from edmg_studio_backend.services.internal_video_models import generate_video_model_frames
    from edmg_studio_backend.services.video_motion_quality import analyze_motion_images

    config = ENGINES[engine]
    lane = ROOT / engine
    segments = lane / "segments"
    segments.mkdir(parents=True, exist_ok=True)
    total = math.ceil(spec["duration"] * FPS / FRAMES_PER_SHOT)
    limit = 1 if smoke else total
    mono, sample_rate, rms = audio_features(spec)
    with FileLock(str(lane / "render.lock"), timeout=0):
        anchor = None
        anchor_hash = None
        for index in range(limit):
            clip = segments / f"{index:04d}.mp4"
            receipt_path = clip.with_suffix(".json")
            start_s = index * FRAMES_PER_SHOT / FPS
            prompt, act_name, camera = shot_prompt(
                index, total, dominant_motion(mono, sample_rate, start_s)
            )
            prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            reusable = False
            if receipt_path.is_file() and clip.is_file() and valid_segment(clip):
                old = json.loads(receipt_path.read_text(encoding="utf-8"))
                reusable = (
                    old.get("fingerprint") == spec["fingerprint"]
                    and old.get("prompt_sha256") == prompt_hash
                    and old.get("input_anchor_sha256") == anchor_hash
                )
            if reusable:
                anchor = last_frame(clip)
                anchor_hash = sha256_image(anchor)
                if anchor_hash == old.get("output_anchor_sha256"):
                    print(f"{engine}: reuse shot {index + 1}/{total} ({act_name})", flush=True)
                    continue
                reusable = False

            state = {
                "engine": engine,
                "stage": "smoke" if smoke else "full",
                "status": "rendering",
                "shot": index + 1,
                "shots": total,
                "start_s": start_s,
                "act": act_name,
                "updated_at": time.time(),
            }
            save_json(lane / "progress.json", state)
            print(json.dumps(state), flush=True)
            evidence = None
            generated = None
            used_seed = None
            for attempt in range(4):
                used_seed = BASE_SEED + index + attempt * 100000
                attempt_prompt = prompt
                if attempt:
                    attempt_prompt += (
                        " Maintain visible continuous walking, camera translation, drifting fog, and changing "
                        "foreground parallax throughout the entire shot; do not produce a still image or long hold."
                    )
                generated = generate_video_model_frames(
                    engine=engine,
                    video_model_dir=MODELS / "video" / config["model_id"],
                    base_model_dir=MODELS / "diffusers/hf_sd15_internal",
                    init_image=anchor,
                    prompt=attempt_prompt,
                    negative_prompt=NEGATIVE,
                    width=WIDTH,
                    height=HEIGHT,
                    num_frames=FRAMES_PER_SHOT + 1,
                    fps=FPS,
                    steps=config["steps"],
                    cfg=config["cfg"],
                    seed=used_seed,
                    device=f"cuda:{config['gpu']}",
                    dtype="bfloat16",
                    cpu_offload=True,
                    decode_chunk_size=4,
                    workspace=lane,
                    generation_mode="auto",
                    chunk_frames=FRAMES_PER_SHOT + 1,
                )
                frames = generated[1:FRAMES_PER_SHOT + 1] if anchor is not None else generated[:FRAMES_PER_SHOT]
                evidence = analyze_motion_images(frames, fps=FPS)
                if evidence["status"] == "pass":
                    break
            if evidence is None or evidence["status"] != "pass" or generated is None:
                raise RuntimeError(f"{engine} shot {index} failed native motion validation: {evidence}")
            frames = apply_audio_modulation(frames, rms, index * FRAMES_PER_SHOT)
            temporary = clip.with_name(clip.stem + ".partial.mp4")
            encode_frames(frames, temporary)
            if not valid_segment(temporary):
                raise RuntimeError(f"Encoded shot {index} failed validation")
            os.replace(temporary, clip)
            output_anchor = last_frame(clip)
            output_anchor_hash = sha256_image(output_anchor)
            save_json(receipt_path, {
                "fingerprint": spec["fingerprint"],
                "engine": engine,
                "model_id": config["model_id"],
                "shot": index,
                "start_s": start_s,
                "act": act_name,
                "camera": camera,
                "seed": used_seed,
                "prompt": prompt,
                "prompt_sha256": prompt_hash,
                "negative_prompt": NEGATIVE,
                "input_anchor_sha256": anchor_hash,
                "output_anchor_sha256": output_anchor_hash,
                "native_motion": evidence,
                "frames": FRAMES_PER_SHOT,
            })
            anchor = output_anchor
            anchor_hash = output_anchor_hash
        if smoke:
            save_json(lane / "progress.json", {
                "engine": engine,
                "stage": "smoke",
                "status": "complete",
                "shot": 1,
                "shots": total,
                "reusable_for_full": True,
            })
            print(f"SMOKE COMPLETE {engine}; first shot is reusable by the full render", flush=True)
            return None
        return finish(engine, spec, total, lane, segments, cv2, np)


def finish(engine: str, spec: dict, count: int, lane: Path, segments: Path, cv2, np) -> Path:
    config = ENGINES[engine]
    concat = lane / "full-concat.txt"
    concat.write_text("".join(f"file 'segments/{index:04d}.mp4'\n" for index in range(count)), encoding="ascii")
    output = lane / f"The-End-Cosmic-Horror-{config['label']}.mp4"
    temporary = output.with_name(output.stem + ".partial.mp4")
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
            "-i", str(AUDIO), "-map", "0:v:0", "-map", "1:a:0", "-t", f"{spec['duration']:.9f}",
            "-vf", f"minterpolate=fps={OUTPUT_FPS}:mi_mode=mci,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=1,fps={OUTPUT_FPS}",
            "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(temporary),
        ],
        check=True,
        timeout=3600,
    )
    info = probe(temporary)
    for kind in ("video", "audio"):
        stream = next(item for item in info["streams"] if item["codec_type"] == kind)
        if abs(float(stream["duration"]) - spec["duration"]) > 1 / OUTPUT_FPS + 0.01:
            raise RuntimeError(f"Final {kind} duration mismatch: {stream['duration']}")
    os.replace(temporary, output)
    capture = cv2.VideoCapture(str(output))
    samples = []
    try:
        for position in np.linspace(0.03, 0.97, 8):
            capture.set(cv2.CAP_PROP_POS_MSEC, float(position) * spec["duration"] * 1000)
            ok, frame = capture.read()
            if not ok or float(frame.std()) < 2:
                raise RuntimeError("Output is blank or could not be decoded")
            samples.append(frame)
    finally:
        capture.release()
    sheet = np.vstack((np.hstack(samples[:4]), np.hstack(samples[4:])))
    cv2.imwrite(str(lane / "full-contact-sheet.jpg"), sheet)
    receipt = {
        "fingerprint": spec["fingerprint"],
        "engine": engine,
        "model_id": config["model_id"],
        "status": "complete",
        "duration": spec["duration"],
        "segments": count,
        "output": str(output),
        "output_sha256": sha256_file(output),
        "ffprobe": info,
        "continuity": "Each shot after the first uses the prior accepted final frame as its image anchor.",
        "audio_modulation": "Smoothed source RMS controls sub-one-percent zoom and restrained luminance.",
    }
    save_json(output.with_suffix(".receipt.json"), receipt)
    save_json(lane / "progress.json", {"engine": engine, "stage": "full", "status": "complete", "output": str(output)})
    print(json.dumps(receipt, indent=2), flush=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=ENGINES, required=True)
    stage = parser.add_mutually_exclusive_group(required=True)
    stage.add_argument("--check", action="store_true")
    stage.add_argument("--smoke", action="store_true")
    stage.add_argument("--full", action="store_true")
    args = parser.parse_args()
    try:
        configure_environment()
        spec = preflight(args.engine)
        if args.check:
            print(json.dumps(spec, indent=2))
            return 0
        render(args.engine, args.smoke, spec)
        return 0
    except Exception as error:
        traceback.print_exc()
        if not args.check:
            progress_path = ROOT / args.engine / "progress.json"
            progress = {}
            if progress_path.is_file():
                try:
                    progress = json.loads(progress_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    progress = {}
            progress.update({
                "engine": args.engine,
                "stage": "smoke" if args.smoke else "full",
                "status": "failed",
                "error_type": type(error).__name__,
                "error": str(error),
                "updated_at": time.time(),
            })
            save_json(progress_path, progress)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
