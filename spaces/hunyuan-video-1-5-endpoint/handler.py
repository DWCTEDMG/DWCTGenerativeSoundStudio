import base64
import os
import tempfile
import time
import torch
from diffusers import HunyuanVideo15Pipeline
from diffusers.utils import export_to_video

MODEL = "hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_t2v"

class EndpointHandler:
    def __init__(self, path=""):
        self.pipe = HunyuanVideo15Pipeline.from_pretrained(MODEL, torch_dtype=torch.bfloat16).to("cuda")
        self.pipe.vae.enable_tiling()
        print("HunyuanVideo 1.5 endpoint model ready", flush=True)

    def __call__(self, data):
        prompt = data.get("inputs", "")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
            raise ValueError("inputs must be a nonempty prompt of at most 4000 characters")
        params = data.get("parameters", {})
        frames = int(params.get("num_frames", 17))
        steps = int(params.get("num_inference_steps", 20))
        seed = int(params.get("seed", 42))
        if frames not in (9, 17, 25, 33, 49, 65, 81, 97, 121) or not 1 <= steps <= 50:
            raise ValueError("Unsupported frame count or inference steps")
        started = time.perf_counter()
        with torch.inference_mode():
            video = self.pipe(prompt=prompt, height=480, width=832, num_frames=frames,
                num_inference_steps=steps, generator=torch.Generator(device="cuda").manual_seed(seed)).frames[0]
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as output:
            output_path = output.name
        try:
            export_to_video(video, output_path, fps=24)
            with open(output_path, "rb") as output:
                encoded = base64.b64encode(output.read()).decode("ascii")
        finally:
            os.unlink(output_path)
        return {"video_base64": encoded, "mime_type": "video/mp4", "frames": len(video),
                "fps": 24, "seed": seed, "model": MODEL, "provider": "huggingface_endpoint",
                "device": torch.cuda.get_device_name(), "elapsed_seconds": time.perf_counter()-started}
