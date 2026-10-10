---
title: Nemotron Omni Direct ZeroGPU
emoji: 🎬
colorFrom: green
colorTo: indigo
sdk: gradio
sdk_version: 6.30.0
app_file: app.py
short_description: Direct Nemotron BF16 inference on ZeroGPU
python_version: "3.12"
startup_duration_timeout: 1h
models:
- nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-BF16
---
Runs Nemotron Omni BF16 directly on ZeroGPU xlarge. No external inference endpoint. Studio can use the OpenAI-compatible /v1 API. MCP is exposed at /gradio_api/mcp/.
The NVFP4 dedicated endpoint remains a separate deployment; this Space uses the BF16 variant for PyTorch compatibility.
