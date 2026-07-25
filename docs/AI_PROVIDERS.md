# AI Providers (cloud-first, upgradeable)

EDMG Studio defaults to **NVIDIA Nemotron cloud** via `nemotron_cloud`, but provider
selection is available directly in Studio `Settings` instead of only through environment variables.

## Default (recommended): NVIDIA Nemotron cloud

```bash
EDMG_AI_MODE=local
EDMG_AI_PROVIDER=nemotron_cloud
EDMG_AI_OPENAI_COMPAT_BASE_URL=https://integrate.api.nvidia.com/v1
EDMG_AI_OPENAI_COMPAT_MODEL=nvidia/llama-3.1-nemotron-ultra-253b-v1
```

Store the NVIDIA API key in Studio Settings → Tokens (`openai_compat_api_key`).

## Local Ollama

```bash
EDMG_AI_MODE=local
EDMG_AI_PROVIDER=ollama
EDMG_AI_OLLAMA_URL=http://127.0.0.1:11434
EDMG_AI_OLLAMA_MODEL=nemotron-3-ultra:cloud
```

On Linux Lightning hosts, `bash scripts/setup_linux_ollama.sh` installs the Ollama sidecar.
Use `qwen3:4b` on lower-spec CPU-only or low-memory systems.

## OpenAI-compatible (local or cloud)

Use this when pointing EDMG to an OpenAI-compatible server such as:

- LM Studio local server
- llama.cpp server
- LocalAI
- vLLM / TGI / OpenWebUI / etc.
- a cloud provider with OpenAI-compatible endpoints

Common base URLs:

- LM Studio: `http://127.0.0.1:1234/v1`
- llama.cpp server: `http://127.0.0.1:8080/v1`
- Groq: `https://api.groq.com/openai/v1`
- Together: `https://api.together.xyz/v1`

```bash
EDMG_AI_MODE=local
EDMG_AI_PROVIDER=openai_compat
EDMG_AI_OPENAI_COMPAT_BASE_URL=https://integrate.api.nvidia.com/v1
EDMG_AI_OPENAI_COMPAT_MODEL=nvidia/llama-3.1-nemotron-ultra-253b-v1
EDMG_AI_OPENAI_COMPAT_API_KEY=...  # if required
```

Some gateways mirror Ollama tags instead of OpenAI-style aliases. If your server expects
`qwen3:8b` or another identifier, override `EDMG_AI_OPENAI_COMPAT_MODEL` accordingly.

Studio stores the OpenAI-compatible API key through its secret-storage path so
you do not have to keep it in plain-text environment variables.

## External AI service (advanced)

If you deploy the optional EDMG AI service as a separate FastAPI process, set:

```bash
EDMG_AI_MODE=http
EDMG_AI_BASE_URL=http://127.0.0.1:7862
```

## Rule-based fallback

If you want to avoid a model dependency for planning, Studio also supports:

```bash
EDMG_AI_MODE=local
EDMG_AI_PROVIDER=rule_based
```

## Recommended local stack

- Planner default: NVIDIA Nemotron Ultra via `nemotron_cloud`
- Local Ollama planner: `nemotron-3-ultra:cloud` or low-resource `qwen3:4b`
- Broad still-image default: SDXL Base 1.0
- Fast still-image option: SD3.5 Large Turbo
- Reference still guidance: SD3.5 ControlNet Blur, Canny, and Depth
- Primary HF video backend: Wan2.2 TI2V 5B
- Short image-to-video fallback: SVD XT Img2Vid

## Hardware tiers

- Low-spec: `qwen3:4b` + SDXL Base 1.0
- Mid-range: `qwen3:8b` + SDXL Base 1.0 + SD3.5 Large Turbo + SD3.5 Blur/Canny
- High-end: `qwen3:8b` + SDXL Base 1.0 + SD3.5 Large Turbo + SD3.5 Blur/Canny/Depth + Wan2.2 TI2V 5B
