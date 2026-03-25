# AI Providers (Local-first, upgradeable)

EDMG Studio defaults to **local AI** via Ollama, but provider selection is now
available directly in Studio `Settings` instead of only through environment variables.

## Default (recommended): Ollama

```bash
EDMG_AI_MODE=local
EDMG_AI_PROVIDER=ollama
EDMG_AI_OLLAMA_URL=http://127.0.0.1:11434
EDMG_AI_OLLAMA_MODEL=qwen2.5:3b-instruct
```

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
EDMG_AI_OPENAI_COMPAT_BASE_URL=http://127.0.0.1:1234/v1
EDMG_AI_OPENAI_COMPAT_MODEL=...
EDMG_AI_OPENAI_COMPAT_API_KEY=...  # if required
```

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
