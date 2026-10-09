---
library_name: diffusers
tags:
- custom-handler
- text-to-video
base_model: hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_t2v
---

# Studio HunyuanVideo 1.5 endpoint

Deployment adapter loading the upstream HunyuanVideo 1.5 weights on the server. Weights and their license remain in the upstream repository.

POST JSON: `{"inputs":"A cinematic video description","parameters":{"seed":42,"num_frames":17,"num_inference_steps":20}}`

Returns JSON containing `video_base64` (MP4), MIME type, actual frame count, fps, model, GPU device and timing. This API needs an adapter to Studio's existing render-worker protocol; creating the endpoint does not connect it to Studio automatically.
