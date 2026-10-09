---
title: Studio HunyuanVideo 1.5 ZeroGPU
emoji: 🎬
colorFrom: purple
colorTo: blue
sdk: gradio
sdk_version: 6.30.0
app_file: app.py
python_version: "3.12"
startup_duration_timeout: 1h
short_description: HunyuanVideo 1.5 text-to-video previews on ZeroGPU
models:
- hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_t2v
---

Direct PyTorch inference on ZeroGPU with a full 96 GB allocation. Uses the HunyuanVideo 1.5 480p text-to-video checkpoint in Diffusers format. This is a short-preview demo; Studio's durable render service requires a separate integration adapter. No weights are downloaded onto your workstation.

API: discover the Gradio schema and call `/generate` with prompt, seed, frames and steps. Returns an MP4 and generation details. GPU duration scales with frames and steps, based on measured short-preview timings, with a maximum of 240 seconds. A 17-frame, 20-step render completed in 35.9 seconds and all 17 frames decoded successfully. Longer settings still require separate qualification.
