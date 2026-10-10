"""Local CUDA-only NVIDIA Director services. Run in the isolated WSL environment.

Weights stay on local storage. Requests are serialized and model residency ends
after each request so the video renderer can use the GPUs again.
"""
from __future__ import annotations

import gc
import inspect
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(os.environ.get("EDMG_LOCAL_NVIDIA_MODELS", Path.home() / "edmg/models/director-nvidia"))
MODELS = {
    "nemotron": ("nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-BF16", "nemotron-omni-bf16"),
    "cosmos": ("nvidia/Cosmos-Reason2-8B", "cosmos-reason2-8b"),
}
app = FastAPI(title="Studio local NVIDIA CUDA services")
lock = threading.Lock()


def release_cuda_cache():
    """Run after generate's frame has gone away, including its last parameter."""
    import torch
    gc.collect()
    if torch.cuda.is_available():
        for index in range(torch.cuda.device_count()):
            with torch.cuda.device(index):
                torch.cuda.empty_cache()


class Completion(BaseModel):
    model: str | None = None
    messages: list[dict] = Field(min_length=1)
    max_tokens: int = Field(default=1024, ge=1, le=8192)
    stream: bool = False


def adapt_nemotron(model):
    """Preserve upstream mask behavior and put each Mamba cache on its layer GPU."""
    from transformers.cache_utils import Cache
    remote = sys.modules[model.language_model.__class__.__module__]
    if not remote.is_fast_path_available:
        # Transformers 5.19 removed the legacy names used by NVIDIA's custom
        # model. Load the published CUDA implementations explicitly.
        from kernels import get_kernel
        from transformers.integrations.hub_kernels import resolve_internal_import
        conv = get_kernel("kernels-community/causal-conv1d", version=1)
        mamba = get_kernel("kernels-community/mamba-ssm", version=1)
        functions = {
            "causal_conv1d_fn": conv.causal_conv1d_fn,
            "causal_conv1d_update": conv.causal_conv1d_update,
            "selective_state_update": resolve_internal_import(mamba, "ops.triton.selective_state_update.selective_state_update"),
            "mamba_chunk_scan_combined": resolve_internal_import(mamba, "ops.triton.ssd_combined.mamba_chunk_scan_combined"),
            "mamba_split_conv1d_scan_combined": resolve_internal_import(mamba, "ops.triton.ssd_combined.mamba_split_conv1d_scan_combined"),
        }
        if not all(callable(function) for function in functions.values()):
            raise RuntimeError("Nemotron CUDA Mamba kernels are incomplete; refusing reference-path inference")
        for name, function in functions.items():
            setattr(remote, name, function)
        remote.is_fast_path_available = True
    # The enclosing custom Omni class does not advertise SDPA support, but its
    # language backbone does. Avoid materializing quadratic attention matrices.
    model.language_model.config._attn_implementation = "sdpa"
    for layer in model.language_model.backbone.layers:
        if getattr(layer, "block_type", None) == "attention":
            layer.mixer.config._attn_implementation = "sdpa"
    cache = remote.NemotronHHybridDynamicCache
    if not hasattr(cache, "get_query_offset"):
        cache.get_query_offset = Cache.get_query_offset
    # The class is reused across requests: replace our closure instead of stacking it.
    original_init = getattr(cache, "_studio_original_init", cache.__init__)
    cache._studio_original_init = original_init
    devices = {index: next(layer.parameters()).device
               for index, layer in enumerate(model.language_model.backbone.layers)}

    def init(instance, *args, **kwargs):
        original_init(instance, *args, **kwargs)
        for index, device in devices.items():
            instance.conv_states[index] = instance.conv_states[index].to(device)
            instance.ssm_states[index] = instance.ssm_states[index].to(device)
    cache.__init__ = init
    original_mask = remote.create_causal_mask
    parameters = inspect.signature(original_mask).parameters
    if "inputs_embeds" in parameters and "input_embeds" not in parameters:
        def mask(**kwargs):
            if "input_embeds" in kwargs:
                kwargs["inputs_embeds"] = kwargs.pop("input_embeds")
            if "cache_position" not in parameters:
                kwargs.pop("cache_position", None)
            return original_mask(**kwargs)
        remote.create_causal_mask = mask


def generate(role: str, payload: Completion):
    import torch
    from transformers import AutoConfig, AutoModel, AutoModelForCausalLM, AutoProcessor, AutoTokenizer, Qwen3VLForConditionalGeneration

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required; CPU inference is disabled")
    release_cuda_cache()
    model_id, folder = MODELS[role]
    path = ROOT / folder
    if not (path / "model.safetensors.index.json").is_file():
        raise RuntimeError(f"Model download is incomplete: {path}")
    required = {1: 40, 2: 40} if role == "nemotron" else {0: 24}
    for device, gib in required.items():
        free, _ = torch.cuda.mem_get_info(device)
        if free < gib * 1024**3:
            raise RuntimeError(f"GPU {device} needs {gib} GiB free; finish other GPU work first")
    model = backbone = processor = tokenizer = inputs = output = parameter = None
    started = time.monotonic()
    try:
        print(f"Loading local {role} processor", flush=True)
        processor = AutoProcessor.from_pretrained(path, trust_remote_code=True, local_files_only=True,
                                                  fix_mistral_regex=True)
        tokenizer = AutoTokenizer.from_pretrained(path, trust_remote_code=True, local_files_only=True,
                                                  fix_mistral_regex=True)
        options = dict(torch_dtype=torch.bfloat16, low_cpu_mem_usage=True, local_files_only=True)
        if role == "nemotron":
            print("Loading pinned RADIO code and Nemotron weights on GPUs 1 and 2", flush=True)
            from kernels import get_kernel
            from transformers.integrations import hub_kernels
            # Preflight before loading 66 GB of weights; NVIDIA's remote code
            # calls lazy_load_kernel with these older module names.
            for name in ("causal-conv1d", "mamba-ssm"):
                hub_kernels._KERNEL_MODULE_MAPPING[name] = get_kernel(f"kernels-community/{name}", version=1)
            from transformers.dynamic_module_utils import get_class_from_dynamic_module
            config = AutoConfig.from_pretrained(path, trust_remote_code=True, local_files_only=True)
            radio = get_class_from_dynamic_module("hf_model.RADIOModel", "nvidia/C-RADIOv4-H",
                revision="0057b339059c0b9e1b4ba996f975410ebbfdfcc8", local_files_only=True)
            AutoModel.register(type(config.vision_config), radio, exist_ok=True)
            config.vision_config.auto_map = {}
            model = AutoModelForCausalLM.from_pretrained(path, config=config, trust_remote_code=True,
                device_map="balanced", max_memory={0: 0, 1: "43GiB", 2: "43GiB", "cpu": 0},
                attn_implementation="eager", **options).eval()
            adapt_nemotron(model)
            # Nemotron's custom processor accepts rendered text, unlike Qwen VL.
            text = tokenizer.apply_chat_template(payload.messages, tokenize=False,
                add_generation_prompt=True, enable_thinking=False)
            inputs = processor(text=text, return_tensors="pt")
        else:
            print("Loading Cosmos weights on GPU 0", flush=True)
            model = Qwen3VLForConditionalGeneration.from_pretrained(path,
                device_map={"": 0}, attn_implementation="sdpa", **options).eval()
            inputs = processor.apply_chat_template(payload.messages, tokenize=True,
                add_generation_prompt=True, return_dict=True, return_tensors="pt")
        mapping = getattr(model, "hf_device_map", {})
        if any(str(device) in {"cpu", "disk"} for device in mapping.values()):
            raise RuntimeError("Model placement included CPU/disk; CUDA-only placement required")
        actual_devices = {}
        for parameter in model.parameters():
            if parameter.device.type != "cuda":
                raise RuntimeError(f"Model parameter remains on {parameter.device}; CUDA-only placement required")
            key = str(parameter.device)
            actual_devices[key] = actual_devices.get(key, 0) + 1
        backbone = model.language_model if role == "nemotron" else model
        device = backbone.get_input_embeddings().weight.device
        allowed = {"input_ids", "attention_mask", "pixel_values", "pixel_values_videos"}
        allowed.update({"sound_clips", "sound_length"} if role == "nemotron" else
                       {"image_grid_thw", "video_grid_thw", "second_per_grid_ts"})
        inputs = {key: value.to(device) if isinstance(value, torch.Tensor) else value
                  for key, value in inputs.items() if key in allowed}
        print(f"Generating local {role} response", flush=True)
        generation_started = time.monotonic()
        with torch.inference_mode():
            output = model.generate(**inputs, max_new_tokens=payload.max_tokens,
                do_sample=False, pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id)
        count = inputs["input_ids"].shape[-1]
        content = tokenizer.decode(output[0, count:], skip_special_tokens=True)
        receipt = {"provider": "local_wsl_cuda", "model": model_id,
            "elapsed_s": round(time.monotonic()-started, 2), "device_map": mapping,
            "load_s": round(generation_started-started, 2),
            "generation_s": round(time.monotonic()-generation_started, 2),
            "parameter_devices": actual_devices,
            "devices": {str(i): torch.cuda.get_device_name(i) for i in required},
            "output_tokens": int(output.shape[-1]-count)}
        print(json.dumps(receipt), flush=True)
        return content, receipt
    finally:
        # Clear the cache adapter's closure too; it retains only device objects.
        del model, backbone, processor, tokenizer, inputs, output, parameter
        gc.collect()
        for device in required:
            with torch.cuda.device(device):
                torch.cuda.empty_cache()


@app.get("/health")
def health():
    return {"status": "ready", "provider": "local_wsl_cuda", "busy": lock.locked(),
        "models": {role: {"id": model_id, "path": str(ROOT/folder),
            "downloaded": complete_download(ROOT/folder)}
            for role, (model_id, folder) in MODELS.items()}}


def complete_download(path):
    try:
        index = json.loads((path/"model.safetensors.index.json").read_text())
        return all((path/name).is_file() for name in set(index["weight_map"].values())) and not any(
            (path/".cache/huggingface/download").rglob("*.incomplete"))
    except (OSError, ValueError, KeyError):
        return False


@app.get("/{role}/v1/models")
def models(role: str):
    if role not in MODELS:
        raise HTTPException(404, "Unknown local model")
    return {"object": "list", "data": [{"id": MODELS[role][0], "object": "model", "owned_by": "nvidia"}]}


@app.post("/{role}/v1/chat/completions")
def completion(role: str, payload: Completion):
    if role not in MODELS:
        raise HTTPException(404, "Unknown local model")
    if payload.stream:
        raise HTTPException(400, "Use stream=false")
    if payload.model not in (None, MODELS[role][0]):
        raise HTTPException(400, "Requested model does not match the local route")
    if not lock.acquire(blocking=False):
        raise HTTPException(503, "Local NVIDIA inference is busy; retry when the current request finishes")
    try:
        content, receipt = generate(role, payload)
        return {"id": "chatcmpl-"+uuid.uuid4().hex, "object": "chat.completion",
            "created": int(time.time()), "model": MODELS[role][0],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                "finish_reason": "stop"}], "studio_receipt": receipt}
    except (RuntimeError, ValueError) as exc:
        print(f"Local {role} request failed: {type(exc).__name__}: {exc}", flush=True)
        raise HTTPException(503, str(exc)) from exc
    finally:
        release_cuda_cache()
        lock.release()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("EDMG_LOCAL_NVIDIA_PORT", "8011")))
