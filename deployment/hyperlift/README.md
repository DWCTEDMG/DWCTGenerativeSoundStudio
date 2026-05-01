# Hyperlift deployment paths

These Dockerfiles are intended for Spaceship Starlight Hyperlift, which builds
from the repository root and asks for a Dockerfile path in the UI.

## Recommended app

If you want to expose the main EDMG Studio backend on a custom domain, use:

- Dockerfile path: `deployment/hyperlift/backend.Dockerfile`

This exposes the FastAPI backend and starts it on `0.0.0.0:$PORT`.
The Hyperlift backend image is intentionally lean and does not install the
local `studio_bundle` runtime.

Set these environment variables on the backend app:

- `PORT=8080`
- `EDMG_AI_MODE=http`
- `EDMG_AI_BASE_URL=https://<your-ai-service-domain>`

## Optional AI-only app

If you only want the lightweight EDMG AI service on a custom domain, use:

- Dockerfile path: `deployment/hyperlift/ai-service.Dockerfile`

This exposes the standalone AI service and starts it on `0.0.0.0:$PORT`.

## Important limitation

These containers do not bundle Ollama, vLLM, llama.cpp, or large model weights.
If you want hosted inference, point the app at an external provider or add a
separate model-serving stack.

Useful environment variables in Hyperlift:

- `PORT=8080`
- `EDMG_AI_MODE=http`
- `EDMG_AI_BASE_URL=https://<your-edmg-ai-service-domain>`
- `EDMG_AI_PROVIDER=openai_compat`
- `EDMG_AI_OPENAI_COMPAT_BASE_URL=https://<your-model-endpoint>/v1`
- `EDMG_AI_OPENAI_COMPAT_MODEL=qwen3-8b`
- `EDMG_AI_OPENAI_COMPAT_API_KEY=<optional>`
