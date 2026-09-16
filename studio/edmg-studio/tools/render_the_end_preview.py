from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import soundfile as sf

STUDIO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDIO / "python_backend"))
from edmg_studio_backend.services.ltx_25_runtime import build_command
from edmg_studio_backend.services.video_motion_quality import analyze_motion_images
from PIL import Image

PROJECT = STUDIO / "data/projects/8e6d6cc1148045949fff6405b07099e2"
OUTPUT = PROJECT / "outputs/qwen-abstract-preview"
AUDIO = PROJECT / "assets/audio/LANDR-The_End-Balanced-Low-REV_V3.wav"
os.environ["EDMG_LTX25_PYTHON"] = str(STUDIO / "tools/ltx-2.5-env/Scripts/python.exe")
direction = json.loads((OUTPUT / "director-preview.json").read_text(encoding="utf-8"))
native = OUTPUT / "ltx-native.mp4"
command = build_command(
    package_root=STUDIO / "models/internal/video/hf_ltx_25_distilled_internal",
    output_path=native, prompt=direction["compiled"]["prompt"],
    width=512, height=320, num_frames=65, fps=8, seed=1337, offload="cpu",
)
environment = dict(os.environ, CUDA_VISIBLE_DEVICES="2", PYTHONUNBUFFERED="1")
print("Rendering Qwen-directed LTX preview on CUDA2", flush=True)
with (OUTPUT / "ltx-render.log").open("w", encoding="utf-8") as log:
    subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT,
                   check=True, timeout=2400)

audio, sample_rate = sf.read(AUDIO, frames=48000 * 8, always_2d=True)
mono = audio.mean(axis=1)
envelopes = []
for index in range(64):
    part = mono[int(index * sample_rate / 8):int((index + 1) * sample_rate / 8)]
    envelopes.append(float(np.sqrt(np.mean(part * part))))
energy = np.asarray(envelopes)
energy /= max(float(np.percentile(energy, 95)), 1e-6)
energy = np.clip(energy, 0, 1)
for index in range(1, len(energy)):
    energy[index] = 0.6 * energy[index - 1] + 0.4 * energy[index]

capture = cv2.VideoCapture(str(native))
frames = []
while True:
    ok, frame = capture.read()
    if not ok:
        break
    frames.append(frame)
capture.release()
if len(frames) < 64:
    raise RuntimeError(f"Incomplete render: {len(frames)} frames")
motion = analyze_motion_images([Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)) for f in frames], fps=8)
if motion["status"] != "pass":
    raise RuntimeError(f"Native video failed motion validation: {motion}")

modulated = OUTPUT / "audio-reactive-8fps.mp4"
writer = cv2.VideoWriter(str(modulated), cv2.VideoWriter_fourcc(*"mp4v"), 8, (512, 320))
if not writer.isOpened():
    raise RuntimeError("Video writer could not open")
for index, frame in enumerate(frames[:64]):
    level = float(energy[index])
    matrix = cv2.getRotationMatrix2D((256, 160), 0, 1 + 0.025 * level)
    frame = cv2.warpAffine(frame, matrix, (512, 320), borderMode=cv2.BORDER_REFLECT)
    frame = np.clip(frame.astype(np.float32) * (0.94 + 0.12 * level), 0, 255).astype(np.uint8)
    writer.write(frame)
writer.release()
final = OUTPUT / "The-End-Qwen-Abstract-Preview.mp4"
subprocess.run([
    "ffmpeg", "-y", "-v", "error", "-i", str(modulated), "-i", str(AUDIO),
    "-map", "0:v:0", "-map", "1:a:0", "-t", "8",
    "-vf", "minterpolate=fps=24:mi_mode=mci,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=1,fps=24",
    "-frames:v", "192",
    "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(final),
], check=True, timeout=180)
receipt = {"director": direction["provenance"], "renderer": "ltx-pipelines 1.3.0",
           "native_fps": 8, "output_fps": 24, "duration_s": 8,
           "audio_modulation": "Smoothed RMS drives 2.5 percent zoom and gentle brightness",
           "motion_evidence": motion, "output": str(final)}
(OUTPUT / "render-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
print(json.dumps(receipt, indent=2), flush=True)
