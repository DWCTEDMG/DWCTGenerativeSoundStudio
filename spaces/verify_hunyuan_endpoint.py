"""Run with uv --no-project --with huggingface_hub --with httpx --with av.

Uses cached HF authentication; never prints credentials or video base64.
"""
import base64
import io
import time
import av
import httpx
from huggingface_hub import HfApi, get_token

api = HfApi()
last_status = None
deadline = time.monotonic() + 1200
while time.monotonic() < deadline:
    endpoint = api.get_inference_endpoint("hunyuan-video-1-5", namespace="gulle1155")
    status = str(endpoint.status)
    if status != last_status:
        print("Endpoint:", status, flush=True)
        last_status = status
    if status == "running":
        response = httpx.post(endpoint.url, headers={"Authorization": f"Bearer {get_token()}"},
            json={"inputs": "A glowing blue sphere on a dark concert stage", "parameters":
                  {"seed": 42, "num_frames": 9, "num_inference_steps": 2}}, timeout=600)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            payload = payload[0]
        video = base64.b64decode(payload.pop("video_base64"), validate=True)
        with av.open(io.BytesIO(video)) as container:
            decoded = sum(1 for _ in container.decode(video=0))
        assert decoded == payload["frames"] == 9, payload
        print({"http_status": response.status_code, "decoded_frames": decoded,
               "bytes": len(video), **payload}, flush=True)
        break
    if status == "failed":
        raise RuntimeError("Endpoint failed to start; inspect deployment logs")
    time.sleep(30)
else:
    raise TimeoutError("Endpoint did not become ready within 20 minutes")
