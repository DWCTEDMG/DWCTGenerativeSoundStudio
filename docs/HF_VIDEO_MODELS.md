# HF Video Models (Diffusers) — EDMG helper

EDMG ships a small Hugging Face *catalog* of strong video-generation models in Diffusers format and provides
a download + wiring helper for ComfyUI.

## Recommended order

The bundled catalog now treats these as the practical default lanes:

1. `wan2.2-ti2v-5b` for the primary HF text/image-to-video path
2. `svd-xt-img2vid` for short image-to-video fallback clips
3. Hunyuan 1.5, CogVideoX 5B, LTX Video, and Wan2.2 T2V A14B as optional benchmark or advanced lanes

Recommendation priority is determined by the order of the `models` array in
`hf_video_model_catalog.json`. The helper API and CLI now preserve that order
instead of re-sorting it alphabetically.

## Catalog file

- `studio/edmg-studio/python_backend/enhanced_deforum_music_generator/presets/hf_video_model_catalog.json`

## Download + wire from the Gradio UI

In the main UI, open:

- **HF Video Models (Download + Wire)**

Provide:
- a model from the dropdown
- optional HF token (or set `HF_TOKEN`)
- `models_root` (central store)
- optional ComfyUI root

EDMG downloads into:

- `<models_root>/hf_video/<model_name>/`

and wires into:

- ComfyUI: `<comfyui_root>/models/video/<model_name>/`

## Generate a clip with Diffusers (CLI)

Use the unified script:

```bash
python studio/edmg-studio/scripts/run_video_diffusers.py --model-id Wan-AI/Wan2.2-TI2V-5B-Diffusers \
  --prompt "Two cats boxing on a stage" --output outputs/wan.mp4 --device cuda --dtype bfloat16
```

For image-to-video models, add `--image /path/to/image.png`.

Short fallback example:

```bash
python studio/edmg-studio/scripts/run_video_diffusers.py --model-id stabilityai/stable-video-diffusion-img2vid-xt \
  --prompt "Camera push through foggy neon ruins" --image inputs/keyframe.png --output outputs/svd.mp4 --device cuda --dtype float16
```

## Notes

- Video generation needs a modern GPU and a recent `diffusers` release.
- Wan2.2 TI2V 5B is the primary recommended Diffusers backend for longer, higher-value runs.
- SVD XT Img2Vid stays in the catalog as the lighter short-clip fallback.
- For Wan pipelines, the upstream docs suggest torch >= 2.4.
