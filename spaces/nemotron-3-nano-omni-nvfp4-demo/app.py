from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path
from typing import Any

import gradio as gr
from openai import OpenAI


DEFAULT_MODEL = "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4"
DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"


def env(name: str, fallback: str = "") -> str:
    return os.getenv(name, fallback).strip()


def default_base_url() -> str:
    return env("NEMOTRON_BASE_URL", DEFAULT_BASE_URL)


def default_model() -> str:
    return env("NEMOTRON_MODEL", DEFAULT_MODEL)


def allow_public_config() -> bool:
    return env("NEMOTRON_ALLOW_PUBLIC_CONFIG", "0").lower() in {"1", "true", "yes", "on"}


def endpoint_key() -> str:
    return env("NEMOTRON_API_KEY") or env("NVIDIA_API_KEY") or env("HF_TOKEN")


def file_to_data_url(path: str | None) -> str | None:
    if not path:
        return None

    file_path = Path(path)
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def build_content_parts(prompt: str, image: str | None, audio: str | None, video: str | None) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    if image:
        parts.append({"type": "image_url", "image_url": {"url": file_to_data_url(image)}})
    if audio:
        parts.append({"type": "audio_url", "audio_url": {"url": file_to_data_url(audio)}})
    if video:
        parts.append({"type": "video_url", "video_url": {"url": file_to_data_url(video)}})
    parts.append({"type": "text", "text": prompt.strip() or "Describe the supplied media."})
    return parts


def request_extra_body(mode: str, reasoning_budget: int, use_audio_in_video: bool) -> dict[str, Any]:
    if mode == "Thinking":
        budget = max(int(reasoning_budget), 0)
        return {
            "thinking_token_budget": budget + 1024,
            "chat_template_kwargs": {
                "enable_thinking": True,
                "reasoning_budget": budget,
            },
            "mm_processor_kwargs": {"use_audio_in_video": bool(use_audio_in_video)},
        }

    return {
        "top_k": 1,
        "chat_template_kwargs": {"enable_thinking": False},
        "mm_processor_kwargs": {"use_audio_in_video": bool(use_audio_in_video)},
    }


def run_nemotron(
    prompt: str,
    image: str | None,
    audio: str | None,
    video: str | None,
    mode: str,
    use_audio_in_video: bool,
    max_tokens: int,
    reasoning_budget: int,
    temperature: float,
    top_p: float,
    base_url_override: str,
    model_override: str,
) -> str:
    """Analyze text or supplied image, audio or video with Nemotron NVFP4.

    Returns a text response. Instruct disables thinking; Thinking enables it.
    Inference runs on the authenticated dedicated GPU endpoint.
    """

    api_key = endpoint_key()
    if not api_key:
        return (
            "NEMOTRON_API_KEY is not configured for this Space. "
            "Add it as a Hugging Face Space secret before running the demo."
        )

    base_url = base_url_override.strip() if allow_public_config() and base_url_override.strip() else default_base_url()
    model = model_override.strip() if allow_public_config() and model_override.strip() else default_model()
    client = OpenAI(base_url=base_url, api_key=api_key, timeout=600.0, max_retries=15)
    request_kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": build_content_parts(prompt, image, audio, video)}],
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
        "extra_body": request_extra_body(mode, reasoning_budget, use_audio_in_video),
    }
    if mode == "Thinking":
        request_kwargs["top_p"] = float(top_p)

    try:
        response = client.chat.completions.create(**request_kwargs)
        content = response.choices[0].message.content
        return content or "(The endpoint returned an empty message.)"
    except Exception as exc:
        return f"Request failed: {type(exc).__name__}: {exc}"


with gr.Blocks(title="Nemotron 3 Nano Omni NVFP4", fill_width=True) as demo:
    gr.Markdown(
        """
        # Nemotron 3 Nano Omni NVFP4

        Multimodal text, image, audio, and video reasoning through an OpenAI-compatible
        `nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4` endpoint.

        This demo uses the dedicated endpoint GPU. It does not run model inference on ZeroGPU.
        """
    )

    with gr.Row():
        with gr.Column(scale=2):
            prompt = gr.Textbox(
                label="Prompt",
                lines=6,
                value="Describe the supplied media in detail and call out any uncertainty.",
            )
            with gr.Row():
                image = gr.Image(label="Image", type="filepath")
                audio = gr.Audio(label="Audio", type="filepath")
                video = gr.Video(label="Video")
            submit = gr.Button("Run Nemotron", variant="primary")

        with gr.Column(scale=1):
            mode = gr.Radio(["Instruct", "Thinking"], value="Instruct", label="Mode")
            use_audio_in_video = gr.Checkbox(value=False, label="Use audio track inside video")
            max_tokens = gr.Slider(128, 8192, value=1024, step=128, label="Max tokens")
            reasoning_budget = gr.Slider(1024, 16384, value=4096, step=1024, label="Reasoning budget")
            temperature = gr.Slider(0.0, 1.0, value=0.2, step=0.05, label="Temperature")
            top_p = gr.Slider(0.05, 1.0, value=0.95, step=0.05, label="Top p")
            base_url = gr.Textbox(
                label="Endpoint base URL",
                value=default_base_url(),
                interactive=allow_public_config(),
            )
            model = gr.Textbox(
                label="Model ID",
                value=default_model(),
                interactive=allow_public_config(),
            )

    output = gr.Markdown(label="Response")

    gr.Examples(
        examples=[
            ["Summarize this image for a video editor. Mention visible text, objects, and mood."],
            ["Transcribe this audio and summarize the speaker intent."],
            ["Describe the video timeline as shots, camera motion, and likely scene changes."],
        ],
        inputs=[prompt],
    )

    submit.click(
        fn=run_nemotron,
        inputs=[
            prompt,
            image,
            audio,
            video,
            mode,
            use_audio_in_video,
            max_tokens,
            reasoning_budget,
            temperature,
            top_p,
            base_url,
            model,
        ],
        outputs=output,
        api_name="run_nemotron",
    )


if __name__ == "__main__":
    demo.launch(mcp_server=True)
