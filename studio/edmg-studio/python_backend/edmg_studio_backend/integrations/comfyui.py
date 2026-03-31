from __future__ import annotations

import mimetypes
import requests
from typing import Any

# ---------------------------
# Core ComfyUI REST helpers
# ---------------------------

def submit_prompt(comfyui_url: str, workflow: dict[str, Any], client_id: str = "edmg-studio") -> dict[str, Any]:
    r = requests.post(f"{comfyui_url}/prompt", json={"prompt": workflow, "client_id": client_id}, timeout=60)
    r.raise_for_status()
    return r.json()

def get_history(comfyui_url: str, prompt_id: str) -> dict[str, Any]:
    r = requests.get(f"{comfyui_url}/history/{prompt_id}", timeout=60)
    r.raise_for_status()
    return r.json()

def get_object_info(comfyui_url: str) -> dict[str, Any]:
    """Returns ComfyUI node catalog (keys are node class names).

    This is the most reliable way to detect which custom nodes are installed.
    """
    r = requests.get(f"{comfyui_url}/object_info", timeout=60)
    r.raise_for_status()
    return r.json()


def upload_input_image(comfyui_url: str, image_path: str, *, subfolder: str = "edmg", overwrite: bool = True) -> dict[str, Any]:
    mime_type = mimetypes.guess_type(image_path)[0] or "application/octet-stream"
    with open(image_path, "rb") as handle:
        files = {"image": (image_path.split("/")[-1].split("\\")[-1], handle, mime_type)}
        data = {
            "type": "input",
            "subfolder": subfolder,
            "overwrite": "true" if overwrite else "false",
        }
        r = requests.post(f"{comfyui_url}/upload/image", data=data, files=files, timeout=120)
    r.raise_for_status()
    return r.json() if r.content else {}

def download_image_bytes(comfyui_url: str, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
    params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    r = requests.get(f"{comfyui_url}/view", params=params, timeout=60)
    r.raise_for_status()
    return r.content

def extract_output_images(history_payload: dict[str, Any]) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    for _pid, data in (history_payload or {}).items():
        outputs = data.get("outputs", {}) or {}
        for _node, out in outputs.items():
            for im in (out.get("images") or []):
                images.append(im)
    return images

def extract_execution_error(history_payload: dict[str, Any]) -> str | None:
    for _pid, data in (history_payload or {}).items():
        status = data.get("status") or {}
        for item in (status.get("messages") or []):
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            kind, payload = item[0], item[1]
            if kind != "execution_error" or not isinstance(payload, dict):
                continue
            msg = str(payload.get("exception_message") or "").strip()
            node_type = str(payload.get("node_type") or "").strip()
            if msg and node_type:
                return f"{node_type}: {msg}"
            if msg:
                return msg
    return None

def has_nodes(object_info: dict[str, Any], required: list[str]) -> tuple[bool, list[str]]:
    missing = [n for n in required if n not in (object_info or {})]
    return (len(missing) == 0), missing

# ---------------------------
# Workflow builders
# ---------------------------

NodeRef = tuple[str, int]


def _ref(node_id: str, output_index: int = 0) -> list[Any]:
    return [str(node_id), int(output_index)]


def _next_node_id(workflow: dict[str, Any]) -> str:
    numeric = [int(key) for key in workflow.keys() if str(key).isdigit()]
    return str((max(numeric) + 1) if numeric else 1)


def _append_lora_chain(
    workflow: dict[str, Any],
    *,
    model_ref: NodeRef,
    clip_ref: NodeRef,
    loras: list[dict[str, Any]] | None = None,
) -> tuple[NodeRef, NodeRef]:
    current_model = model_ref
    current_clip = clip_ref
    for item in loras or []:
        lora_name = str(item.get("filename") or item.get("name") or "").strip()
        if not lora_name:
            continue
        node_id = _next_node_id(workflow)
        weight = float(item.get("weight", 1.0))
        clip_weight = float(item.get("clip_weight", weight))
        workflow[node_id] = {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": lora_name,
                "strength_model": weight,
                "strength_clip": clip_weight,
                "model": _ref(*current_model),
                "clip": _ref(*current_clip),
            },
        }
        current_model = (node_id, 0)
        current_clip = (node_id, 1)
    return current_model, current_clip


def _append_vae_loader(
    workflow: dict[str, Any],
    *,
    checkpoint_node: str,
    vae_name: str | None = None,
) -> NodeRef:
    if not str(vae_name or "").strip():
        return (checkpoint_node, 2)
    node_id = _next_node_id(workflow)
    workflow[node_id] = {
        "class_type": "VAELoader",
        "inputs": {"vae_name": str(vae_name).strip()},
    }
    return (node_id, 0)


def _append_controlnet_units(
    workflow: dict[str, Any],
    *,
    positive_ref: NodeRef,
    negative_ref: NodeRef,
    units: list[dict[str, Any]] | None = None,
) -> tuple[NodeRef, NodeRef]:
    current_positive = positive_ref
    current_negative = negative_ref
    for unit in units or []:
        controlnet_name = str(unit.get("controlnet_name") or unit.get("model") or "").strip()
        reference_image = str(unit.get("reference_image") or unit.get("image") or "").strip()
        if not controlnet_name or not reference_image:
            continue
        image_node = _next_node_id(workflow)
        workflow[image_node] = {
            "class_type": "LoadImage",
            "inputs": {"image": reference_image, "upload": "image"},
        }
        loader_node = _next_node_id(workflow)
        workflow[loader_node] = {
            "class_type": "ControlNetLoader",
            "inputs": {"control_net_name": controlnet_name},
        }
        apply_node = _next_node_id(workflow)
        workflow[apply_node] = {
            "class_type": "ControlNetApplyAdvanced",
            "inputs": {
                "strength": float(unit.get("strength", 0.8)),
                "start_percent": float(unit.get("start_percent", 0.0)),
                "end_percent": float(unit.get("end_percent", 1.0)),
                "positive": _ref(*current_positive),
                "negative": _ref(*current_negative),
                "control_net": _ref(loader_node, 0),
                "image": _ref(image_node, 0),
            },
        }
        current_positive = (apply_node, 0)
        current_negative = (apply_node, 1)
    return current_positive, current_negative

def default_workflow(
    checkpoint: str,
    prompt: str,
    negative_prompt: str,
    seed: int,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    sampler: str,
    filename_prefix: str = "edmg_studio",
    loras: list[dict[str, Any]] | None = None,
    vae_name: str | None = None,
) -> dict[str, Any]:
    """Basic SD txt2img workflow (single image)."""
    workflow: dict[str, Any] = {
        "3": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
    }
    model_ref, clip_ref = _append_lora_chain(workflow, model_ref=("3", 0), clip_ref=("3", 1), loras=loras)
    vae_ref = _append_vae_loader(workflow, checkpoint_node="3", vae_name=vae_name)
    latent_node = _next_node_id(workflow)
    workflow[latent_node] = {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": width, "height": height, "batch_size": 1},
    }
    pos_node = _next_node_id(workflow)
    workflow[pos_node] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": prompt, "clip": _ref(*clip_ref)},
    }
    neg_node = _next_node_id(workflow)
    workflow[neg_node] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": negative_prompt, "clip": _ref(*clip_ref)},
    }
    sample_node = _next_node_id(workflow)
    workflow[sample_node] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": sampler,
            "scheduler": "normal",
            "denoise": 1,
            "model": _ref(*model_ref),
            "positive": _ref(pos_node, 0),
            "negative": _ref(neg_node, 0),
            "latent_image": _ref(latent_node, 0),
        },
    }
    decode_node = _next_node_id(workflow)
    workflow[decode_node] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": _ref(sample_node, 0), "vae": _ref(*vae_ref)},
    }
    save_node = _next_node_id(workflow)
    workflow[save_node] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": filename_prefix, "images": _ref(decode_node, 0)},
    }
    return workflow


def img2img_workflow(
    checkpoint: str,
    prompt: str,
    negative_prompt: str,
    seed: int,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    sampler: str,
    source_image: str,
    denoise_strength: float = 0.75,
    filename_prefix: str = "edmg_studio_img2img",
    loras: list[dict[str, Any]] | None = None,
    vae_name: str | None = None,
) -> dict[str, Any]:
    workflow: dict[str, Any] = {
        "3": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "4": {"class_type": "LoadImage", "inputs": {"image": source_image, "upload": "image"}},
    }
    model_ref, clip_ref = _append_lora_chain(workflow, model_ref=("3", 0), clip_ref=("3", 1), loras=loras)
    vae_ref = _append_vae_loader(workflow, checkpoint_node="3", vae_name=vae_name)
    encode_node = _next_node_id(workflow)
    workflow[encode_node] = {
        "class_type": "VAEEncode",
        "inputs": {"pixels": _ref("4", 0), "vae": _ref(*vae_ref)},
    }
    pos_node = _next_node_id(workflow)
    workflow[pos_node] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": prompt, "clip": _ref(*clip_ref)},
    }
    neg_node = _next_node_id(workflow)
    workflow[neg_node] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": negative_prompt, "clip": _ref(*clip_ref)},
    }
    sample_node = _next_node_id(workflow)
    workflow[sample_node] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": sampler,
            "scheduler": "normal",
            "denoise": float(denoise_strength),
            "model": _ref(*model_ref),
            "positive": _ref(pos_node, 0),
            "negative": _ref(neg_node, 0),
            "latent_image": _ref(encode_node, 0),
        },
    }
    decode_node = _next_node_id(workflow)
    workflow[decode_node] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": _ref(sample_node, 0), "vae": _ref(*vae_ref)},
    }
    save_node = _next_node_id(workflow)
    workflow[save_node] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": filename_prefix, "images": _ref(decode_node, 0)},
    }
    return workflow


def inpaint_workflow(
    checkpoint: str,
    prompt: str,
    negative_prompt: str,
    seed: int,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    sampler: str,
    source_image: str,
    mask_image: str,
    denoise_strength: float = 0.8,
    filename_prefix: str = "edmg_studio_inpaint",
    loras: list[dict[str, Any]] | None = None,
    vae_name: str | None = None,
) -> dict[str, Any]:
    workflow: dict[str, Any] = {
        "3": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "4": {"class_type": "LoadImage", "inputs": {"image": source_image, "upload": "image"}},
        "5": {"class_type": "LoadImageMask", "inputs": {"image": mask_image, "upload": "image"}},
    }
    model_ref, clip_ref = _append_lora_chain(workflow, model_ref=("3", 0), clip_ref=("3", 1), loras=loras)
    vae_ref = _append_vae_loader(workflow, checkpoint_node="3", vae_name=vae_name)
    encode_node = _next_node_id(workflow)
    workflow[encode_node] = {
        "class_type": "VAEEncodeForInpaint",
        "inputs": {
            "pixels": _ref("4", 0),
            "mask": _ref("5", 0),
            "vae": _ref(*vae_ref),
            "grow_mask_by": 0,
        },
    }
    pos_node = _next_node_id(workflow)
    workflow[pos_node] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": prompt, "clip": _ref(*clip_ref)},
    }
    neg_node = _next_node_id(workflow)
    workflow[neg_node] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": negative_prompt, "clip": _ref(*clip_ref)},
    }
    sample_node = _next_node_id(workflow)
    workflow[sample_node] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": sampler,
            "scheduler": "normal",
            "denoise": float(denoise_strength),
            "model": _ref(*model_ref),
            "positive": _ref(pos_node, 0),
            "negative": _ref(neg_node, 0),
            "latent_image": _ref(encode_node, 0),
        },
    }
    decode_node = _next_node_id(workflow)
    workflow[decode_node] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": _ref(sample_node, 0), "vae": _ref(*vae_ref)},
    }
    save_node = _next_node_id(workflow)
    workflow[save_node] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": filename_prefix, "images": _ref(decode_node, 0)},
    }
    return workflow


def outpaint_workflow(
    checkpoint: str,
    prompt: str,
    negative_prompt: str,
    seed: int,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    sampler: str,
    source_image: str,
    mask_image: str,
    denoise_strength: float = 0.8,
    filename_prefix: str = "edmg_studio_outpaint",
    loras: list[dict[str, Any]] | None = None,
    vae_name: str | None = None,
) -> dict[str, Any]:
    # Outpainting uses the same graph as inpainting after the caller prepares an
    # expanded canvas + mask. The runtime/UI canvas expansion step plugs in later.
    return inpaint_workflow(
        checkpoint=checkpoint,
        prompt=prompt,
        negative_prompt=negative_prompt,
        seed=seed,
        width=width,
        height=height,
        steps=steps,
        cfg=cfg,
        sampler=sampler,
        source_image=source_image,
        mask_image=mask_image,
        denoise_strength=denoise_strength,
        filename_prefix=filename_prefix,
        loras=loras,
        vae_name=vae_name,
    )


def controlnet_workflow(
    checkpoint: str,
    prompt: str,
    negative_prompt: str,
    seed: int,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    sampler: str,
    controlnet_name: str,
    reference_image: str,
    controlnet_strength: float = 0.8,
    start_percent: float = 0.0,
    end_percent: float = 1.0,
    filename_prefix: str = "edmg_studio_cn",
    loras: list[dict[str, Any]] | None = None,
    vae_name: str | None = None,
    controlnet_units: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    workflow: dict[str, Any] = {
        "3": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
    }
    model_ref, clip_ref = _append_lora_chain(workflow, model_ref=("3", 0), clip_ref=("3", 1), loras=loras)
    vae_ref = _append_vae_loader(workflow, checkpoint_node="3", vae_name=vae_name)
    pos_node = _next_node_id(workflow)
    workflow[pos_node] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": prompt, "clip": _ref(*clip_ref)},
    }
    neg_node = _next_node_id(workflow)
    workflow[neg_node] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": negative_prompt, "clip": _ref(*clip_ref)},
    }

    units = list(controlnet_units or [])
    if not units and controlnet_name and reference_image:
        units = [
            {
                "controlnet_name": controlnet_name,
                "reference_image": reference_image,
                "strength": controlnet_strength,
                "start_percent": start_percent,
                "end_percent": end_percent,
            }
        ]
    positive_ref, negative_ref = _append_controlnet_units(
        workflow,
        positive_ref=(pos_node, 0),
        negative_ref=(neg_node, 0),
        units=units,
    )
    latent_node = _next_node_id(workflow)
    workflow[latent_node] = {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": width, "height": height, "batch_size": 1},
    }
    sample_node = _next_node_id(workflow)
    workflow[sample_node] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": sampler,
            "scheduler": "normal",
            "denoise": 1,
            "model": _ref(*model_ref),
            "positive": _ref(*positive_ref),
            "negative": _ref(*negative_ref),
            "latent_image": _ref(latent_node, 0),
        },
    }
    decode_node = _next_node_id(workflow)
    workflow[decode_node] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": _ref(sample_node, 0), "vae": _ref(*vae_ref)},
    }
    save_node = _next_node_id(workflow)
    workflow[save_node] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": filename_prefix, "images": _ref(decode_node, 0)},
    }
    return workflow

def animatediff_workflow(
    checkpoint: str,
    prompt: str,
    negative_prompt: str,
    seed: int,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    sampler: str,
    frames: int,
    motion_model_name: str,
    context_length: int = 16,
    context_overlap: int = 4,
    beta_schedule: str = "autoselect",
    filename_prefix: str = "edmg_studio_ad",
    loras: list[dict[str, Any]] | None = None,
    vae_name: str | None = None,
) -> dict[str, Any]:
    """AnimateDiff Evolved txt2video workflow.

    Requires ComfyUI-AnimateDiff-Evolved custom nodes:
      - ADE_StandardStaticContextOptions
      - ADE_AnimateDiffLoaderGen1
    """
    frames = max(1, int(frames))
    context_length = max(1, int(context_length))
    context_overlap = max(0, int(context_overlap))

    workflow: dict[str, Any] = {
        "3": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
    }
    model_ref, clip_ref = _append_lora_chain(workflow, model_ref=("3", 0), clip_ref=("3", 1), loras=loras)
    vae_ref = _append_vae_loader(workflow, checkpoint_node="3", vae_name=vae_name)
    context_node = _next_node_id(workflow)
    workflow[context_node] = {
        "class_type": "ADE_StandardStaticContextOptions",
        "inputs": {
            "context_length": context_length,
            "context_overlap": context_overlap,
            "fuse_method": "pyramid",
            "use_on_equal_length": True,
            "start_percent": 0.0,
            "guarantee_steps": 0,
        },
    }
    motion_node = _next_node_id(workflow)
    workflow[motion_node] = {
        "class_type": "ADE_AnimateDiffLoaderGen1",
        "inputs": {
            "model": _ref(*model_ref),
            "model_name": motion_model_name,
            "beta_schedule": beta_schedule,
            "context_options": _ref(context_node, 0),
        },
    }
    latent_node = _next_node_id(workflow)
    workflow[latent_node] = {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": width, "height": height, "batch_size": frames},
    }
    pos_node = _next_node_id(workflow)
    workflow[pos_node] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": prompt, "clip": _ref(*clip_ref)},
    }
    neg_node = _next_node_id(workflow)
    workflow[neg_node] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": negative_prompt, "clip": _ref(*clip_ref)},
    }
    sample_node = _next_node_id(workflow)
    workflow[sample_node] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": sampler,
            "scheduler": "normal",
            "denoise": 1,
            "model": _ref(motion_node, 0),
            "positive": _ref(pos_node, 0),
            "negative": _ref(neg_node, 0),
            "latent_image": _ref(latent_node, 0),
        },
    }
    decode_node = _next_node_id(workflow)
    workflow[decode_node] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": _ref(sample_node, 0), "vae": _ref(*vae_ref)},
    }
    save_node = _next_node_id(workflow)
    workflow[save_node] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": filename_prefix, "images": _ref(decode_node, 0)},
    }
    return workflow

def svd_workflow(
    checkpoint: str,
    prompt: str,
    negative_prompt: str,
    seed: int,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    sampler: str,
    svd_checkpoint: str = "svd_xt.safetensors",
    svd_num_frames: int = 14,
    svd_num_steps: int = 25,
    svd_motion_bucket_id: int = 127,
    svd_fps_id: int = 6,
    svd_cond_aug: float = 0.02,
    svd_decoding_t: int = 14,
    device: str = "cuda",
    filename_prefix: str = "edmg_studio_svd",
    loras: list[dict[str, Any]] | None = None,
    vae_name: str | None = None,
) -> dict[str, Any]:
    """txt2img -> Stable Video Diffusion (img2vid).

    Requires ComfyUI-Stable-Video-Diffusion custom nodes:
      - SVDSimpleImg2Vid
    """
    svd_num_frames = max(1, int(svd_num_frames))
    workflow: dict[str, Any] = {
        "3": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
    }
    model_ref, clip_ref = _append_lora_chain(workflow, model_ref=("3", 0), clip_ref=("3", 1), loras=loras)
    vae_ref = _append_vae_loader(workflow, checkpoint_node="3", vae_name=vae_name)
    latent_node = _next_node_id(workflow)
    workflow[latent_node] = {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": width, "height": height, "batch_size": 1},
    }
    pos_node = _next_node_id(workflow)
    workflow[pos_node] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": prompt, "clip": _ref(*clip_ref)},
    }
    neg_node = _next_node_id(workflow)
    workflow[neg_node] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": negative_prompt, "clip": _ref(*clip_ref)},
    }
    sample_node = _next_node_id(workflow)
    workflow[sample_node] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": sampler,
            "scheduler": "normal",
            "denoise": 1,
            "model": _ref(*model_ref),
            "positive": _ref(pos_node, 0),
            "negative": _ref(neg_node, 0),
            "latent_image": _ref(latent_node, 0),
        },
    }
    decode_node = _next_node_id(workflow)
    workflow[decode_node] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": _ref(sample_node, 0), "vae": _ref(*vae_ref)},
    }
    svd_node = _next_node_id(workflow)
    workflow[svd_node] = {
        "class_type": "SVDSimpleImg2Vid",
        "inputs": {
            "image": _ref(decode_node, 0),
            "checkpoint": svd_checkpoint,
            "num_frames": svd_num_frames,
            "num_steps": int(svd_num_steps),
            "motion_bucket_id": int(svd_motion_bucket_id),
            "fps_id": int(svd_fps_id),
            "cond_aug": float(svd_cond_aug),
            "seed": int(seed),
            "decoding_t": int(svd_decoding_t),
            "device": str(device),
        },
    }
    save_node = _next_node_id(workflow)
    workflow[save_node] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": filename_prefix, "images": _ref(svd_node, 0)},
    }
    return workflow
