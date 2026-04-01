# EDMG Studio Backend (v1.1.0)

## Run
```bash
pip install -e ".[studio_bundle]"
edmg-studio-backend serve --host 127.0.0.1 --port 7863
```

## Tests
Install the same backend bundle Studio uses, plus the test extra:

```bash
pip install -e ".[studio_bundle,test]"
python -m pytest enhanced_deforum_music_generator/tests
```

## AI (Ollama by default)

The backend defaults to **EDMG_AI_MODE=local** and will call **Ollama** directly (no separate AI server to run).

Recommended env vars:

```bash
EDMG_AI_MODE=local
EDMG_AI_PROVIDER=ollama
EDMG_AI_OLLAMA_URL=http://127.0.0.1:11434
EDMG_AI_OLLAMA_MODEL=qwen3:8b
```

Use `qwen3:4b` instead on lighter CPU-only or low-memory systems.

If you want an external AI service instead:

```bash
EDMG_AI_MODE=http
EDMG_AI_BASE_URL=http://127.0.0.1:7862
```

OpenAI-compatible option (LM Studio / llama.cpp server / vLLM / Groq / Together, etc.):

```bash
EDMG_AI_MODE=local
EDMG_AI_PROVIDER=openai_compat
EDMG_AI_OPENAI_COMPAT_BASE_URL=http://127.0.0.1:1234/v1
EDMG_AI_OPENAI_COMPAT_MODEL=qwen3-8b
EDMG_AI_OPENAI_COMPAT_API_KEY=...  # if required
```

If your OpenAI-compatible gateway exposes a different model alias, override
`EDMG_AI_OPENAI_COMPAT_MODEL` to match that server.

## Recommended local model stack

- Planner default: `qwen3:8b`
- Low-resource planner: `qwen3:4b`
- Broad still-image default: SDXL Base 1.0
- Fast still-image option: SD3.5 Large Turbo
- Reference still guidance: SD3.5 ControlNet Blur, Canny, and Depth
- Primary HF video backend: Wan2.2 TI2V 5B
- Short image-to-video fallback: SVD XT Img2Vid

## Hardware tiers

- Low-spec: `qwen3:4b` + SDXL Base 1.0
- Mid-range: `qwen3:8b` + SDXL Base 1.0 + SD3.5 Large Turbo + SD3.5 Blur/Canny
- High-end: `qwen3:8b` + SDXL Base 1.0 + SD3.5 Large Turbo + SD3.5 Blur/Canny/Depth + Wan2.2 TI2V 5B

## Integrations
- ComfyUI renders are queued locally.
- Planning/transcription run in-process by default through the selected provider; an external AI service on `7862` is optional.
- EDMG Core is bundled into the Studio backend install/build target; Studio Setup can repair or reinstall it if needed.
- FFmpeg defaults to the Studio-bundled binary when available; `EDMG_FFMPEG_PATH` remains an override.
