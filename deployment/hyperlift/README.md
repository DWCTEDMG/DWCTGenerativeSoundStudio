# Hyperlift deployment paths

These Dockerfiles are intended for Spaceship Starlight Hyperlift, which builds
from the repository root and asks for a Dockerfile path in the UI.

## Recommended app

If you want to expose the main EDMG Studio backend on a custom domain, use:

- Dockerfile path: `deployment/hyperlift/backend.Dockerfile`

This exposes the FastAPI backend and starts it on `0.0.0.0:$PORT`.
The image checks the committed backend lock and performs a frozen `cpu`
profile sync with the `core`, `audio`, `asr`, `internal-video`, and `aws`
capabilities. Python 3.12, uv 0.11.28, and the exact dependency resolution are
therefore the same release inputs used by CI; Hyperlift does not resolve an
independent requirements set.

Set these environment variables on the backend app:

- `PORT=8080`
- `EDMG_STUDIO_BACKEND_HOST=0.0.0.0`
- `EDMG_BACKEND_AUTH_MODE=required`
- `EDMG_BACKEND_AUTH_TOKEN=<generate a long random secret in the Hyperlift secret manager>`
- `EDMG_BACKEND_CORS_ORIGINS=https://<your-studio-frontend-domain>`
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

## Optional Studio-wide TensorRT capability

EDMG Studio supports optional TensorRT acceleration through the shared backend runtime manager. Studio settings provide the global switch; native Render controls can override the preference, precision, and fallback for an individual internal render. Turning TensorRT off preserves the original runtime and does not require TensorRT to be installed.

This area retains its existing runtime and workflow; the shared Studio policy applies only to eligible internal inference components. The SD1.5 VAE decoder has an adapter; other model components remain on their existing runtimes until separately converted and validated. Hosted providers, audio processing, compositing, and exports do not acquire a TensorRT dependency. See the [Studio-wide TensorRT blueprint](../../EDMG_TensorRT_Full_Studio_Wide_Blueprint.md) for component admission and validation requirements.
