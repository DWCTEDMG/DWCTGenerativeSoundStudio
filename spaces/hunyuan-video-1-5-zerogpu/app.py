import spaces
import tempfile
import time
import gradio as gr
import torch
from diffusers import HunyuanVideo15Pipeline
from diffusers.utils import export_to_video

MODEL = "hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_t2v"
pipe = HunyuanVideo15Pipeline.from_pretrained(MODEL, torch_dtype=torch.bfloat16).to("cuda")
pipe.vae.enable_tiling()
print("Hunyuan model loaded; ZeroGPU placement complete", flush=True)

def gpu_duration(prompt, seed, frames, steps):
    # Measured 17 frames / 20 steps at 35.9 s; include cold/decode headroom.
    return min(240, max(20, int(10 + int(steps) * int(frames) / 17 * 2.3)))

@spaces.GPU(duration=gpu_duration, size="xlarge")
def generate(prompt, seed, frames, steps):
    """Generate a short HunyuanVideo 1.5 MP4 on ZeroGPU.

    Args:
        prompt: Description of the video to generate.
        seed: Reproducible random seed.
        frames: Number of frames, one of 9, 17, 25, or 33 (24 fps).
        steps: Denoising steps, from 1 to 50; higher values take longer.

    Returns:
        An MP4 file and a receipt describing the model, GPU and timing.
    """
    if not prompt.strip():
        raise gr.Error("Enter a video description.")
    started = time.perf_counter()
    with torch.inference_mode():
        video = pipe(prompt=prompt, height=480, width=832,
                     num_frames=int(frames), num_inference_steps=int(steps),
                     generator=torch.Generator(device="cuda").manual_seed(int(seed))).frames[0]
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as output:
        path = output.name
    export_to_video(video, path, fps=24)
    return path, f"Generated {len(video)} frames on {torch.cuda.get_device_name()} in {time.perf_counter()-started:.1f}s. Model: {MODEL}"

with gr.Blocks(title="Studio HunyuanVideo 1.5") as demo:
    gr.Markdown("# HunyuanVideo 1.5 · Studio demo\nGenerate short text-to-video previews on dynamically allocated ZeroGPU hardware. Downloads and generation happen on Hugging Face.")
    prompt = gr.Textbox(label="Video description", value="A glowing waveform floating above a dark stage, slow cinematic camera movement")
    with gr.Row():
        seed = gr.Number(label="Seed", value=42, precision=0)
        frames = gr.Dropdown([9, 17, 25, 33], value=17, label="Frames at 24 fps")
        steps = gr.Slider(1, 50, value=20, step=1, label="Inference steps")
    run = gr.Button("Generate video", variant="primary")
    video = gr.Video(label="Preview")
    receipt = gr.Textbox(label="Generation details")
    run.click(generate, [prompt, seed, frames, steps], [video, receipt], api_name="generate")
demo.queue(default_concurrency_limit=1).launch(mcp_server=True)
