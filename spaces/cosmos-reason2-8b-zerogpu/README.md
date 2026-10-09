---
title: Cosmos Reason2 8B ZeroGPU
emoji: 🐠
colorFrom: indigo
colorTo: blue
sdk: gradio
sdk_version: 6.30.0
python_version: "3.12"
app_file: app.py
startup_duration_timeout: 1h
short_description: Cosmos reasoning on ZeroGPU with a Studio API
models:
- nvidia/Cosmos-Reason2-8B
---
Cosmos Reason2 8B runs directly on ZeroGPU. The OpenAI-compatible API is /v1, and MCP is /gradio_api/mcp/. Audio is not supported by Cosmos. Existing bucket configuration is preserved.
