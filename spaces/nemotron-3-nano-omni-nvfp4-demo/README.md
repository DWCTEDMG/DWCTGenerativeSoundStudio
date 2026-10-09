---
title: Nemotron 3 Nano Omni NVFP4 Demo
emoji: 🎬
colorFrom: green
colorTo: indigo
sdk: gradio
sdk_version: 6.30.0
app_file: app.py
short_description: Multimodal Nemotron Omni endpoint demo
python_version: "3.12"
startup_duration_timeout: 30m
hf_oauth: false
---

# Nemotron 3 Nano Omni NVFP4 Demo

This Space is a Gradio demo for `nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4`.

The app is intentionally a thin OpenAI-compatible client. It does not download or load the
21 GB NVFP4 model inside the Space. Point it at NVIDIA-hosted inference, a private vLLM server,
or another compatible endpoint with these Space secrets or environment variables:

| Name | Required | Default | Notes |
| --- | --- | --- | --- |
| `NEMOTRON_API_KEY` | Yes | none | Secret for the hosted endpoint. |
| `NEMOTRON_BASE_URL` | No | `https://integrate.api.nvidia.com/v1` | OpenAI-compatible base URL. |
| `NEMOTRON_MODEL` | No | `nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4` | Served model ID. |
| `NEMOTRON_ALLOW_PUBLIC_CONFIG` | No | `0` | Set to `1` to let visitors override endpoint fields in the UI. |

The demo supports text prompts and optional image, audio, or video uploads. Image uploads are sent
as base64 data URLs. Audio and video are also encoded as data URLs; if your endpoint requires
server-local `file://` media paths instead, deploy the inference server and Space in the same
environment or adapt `build_content_parts` in `app.py`.

## Create and Upload

```bash
hf repos create <namespace>/nemotron-3-nano-omni-nvfp4-demo --type space --space-sdk gradio --public --exist-ok
hf spaces secrets set <namespace>/nemotron-3-nano-omni-nvfp4-demo NEMOTRON_API_KEY=<your-key>
hf upload <namespace>/nemotron-3-nano-omni-nvfp4-demo . --repo-type space --exclude "**/__pycache__/**"
```

For a free personal Hugging Face account, Gradio Spaces may require ZeroGPU creation:

```bash
hf repos create <namespace>/nemotron-3-nano-omni-nvfp4-demo --type space --space-sdk gradio --flavor zero-a10g --public --exist-ok
```

This app does not call `@spaces.GPU`, so it does not reserve GPU time for inference. The actual
compute happens at the configured endpoint.

## ZeroGPU vs Studio GPUs

ZeroGPU is useful for a public Hugging Face demo because Hugging Face allocates a GPU only while a
decorated Gradio function is running. It is not the same thing as exposing the model as a durable
OpenAI-compatible server for EDMG Studio.

Use these paths for the two jobs:

| Goal | Recommended path |
| --- | --- |
| Public demo on Hugging Face | Create the Space with `--flavor zero-a10g`. Keep this app as an endpoint proxy, or build a separate direct ZeroGPU variant with `import spaces`, module-scope model loading, and `@spaces.GPU`. |
| Studio using your local or rented GPUs | Run Nemotron with vLLM, TensorRT-LLM, SGLang, or another OpenAI-compatible server on those GPUs, then set Studio's Director endpoint to that server URL. |
| Studio calling the Space itself | Possible, but it needs a Studio Gradio-client adapter or an OpenAI-compatible API shim in front of the Space. Studio's current Director server path expects `/v1/chat/completions`. |

For this model, NVIDIA lists NVFP4 as a 21 GB precision target. That makes it plausible for
ZeroGPU hardware, but a direct ZeroGPU model-loading Space should be validated live from Space logs
because the repo uses custom model code and multimodal processing.

## Use With EDMG Studio

EDMG Studio can use the same Nemotron endpoint as its AI Director when the endpoint exposes an
OpenAI-compatible `/v1/chat/completions` API.

In Studio Settings, set the primary Director execution to hosted/server mode and use:

| Studio setting | Value |
| --- | --- |
| Endpoint | `https://integrate.api.nvidia.com/v1` or your GPU server URL |
| Server model | `nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4` |
| Credential | `EDMG_NEMOTRON_API_KEY`, `EDMG_AI_NVIDIA_API_KEY`, or the Studio secret-store NVIDIA key |

For local or rented GPUs, run the model with vLLM, TensorRT-LLM, SGLang, or another compatible
server, then point both Studio and this Space at that server's base URL. The Space remains a demo
surface; Studio remains the production creative workflow.

## Hugging Face Dedicated Endpoint

The dedicated endpoint console for this account is:

`https://endpoints.huggingface.co/gulle1155/endpoints/dedicated?resetAccount=true`

Use a dedicated endpoint when you want Studio to use Hugging Face-managed GPUs without depending on
Gradio's Space API. Deploy `nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4` with an
OpenAI-compatible engine such as vLLM, SGLang, or a custom container that exposes:

`/v1/chat/completions`

After deployment, Hugging Face will provide an endpoint host similar to:

`https://<endpoint-id>.<region>.<cloud>.endpoints.huggingface.cloud`

The live endpoint created for this workspace is:

`https://6ac87f4453d27c9b5cb0cba8.endpoints.huggingface.cloud`

For OpenAI-compatible clients, use the base URL with `/v1`, for example:

`https://<endpoint-id>.<region>.<cloud>.endpoints.huggingface.cloud/v1`

For this endpoint, use:

`https://6ac87f4453d27c9b5cb0cba8.endpoints.huggingface.cloud/v1`

Then set both apps to the same target:

| Consumer | Setting |
| --- | --- |
| EDMG Studio | Primary Director endpoint = `<dedicated-endpoint>/v1` |
| This Space | `NEMOTRON_BASE_URL=<dedicated-endpoint>/v1` |
| Both | Model ID = `nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4` |

This is the clean GPU path for Studio: Hugging Face owns the GPU endpoint, Studio owns the creative
workflow, and the Space remains a public demo or smoke-test surface.
