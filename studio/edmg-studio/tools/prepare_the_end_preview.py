from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

STUDIO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDIO / "python_backend"))

from edmg_studio_backend.domain.director_scene import DirectorDocument, compile_scene
from edmg_studio_backend.services.engine_packages import package_manifest, validate_package
from edmg_studio_backend.services.llama_cpp_director import LlamaCppDirectorBackend
from edmg_studio_backend.services.qwen_director import validate_proposal

PROJECT = "8e6d6cc1148045949fff6405b07099e2"
API = f"http://127.0.0.1:7863/v1/projects/{PROJECT}"
output = STUDIO / "data" / "projects" / PROJECT / "outputs" / "qwen-abstract-preview"
output.mkdir(parents=True, exist_ok=True)
model_id = "hf_qwen3_vl_8b_gguf_director"
model_root = STUDIO / "models" / "internal" / "director" / model_id
validation = validate_package(model_root, package_manifest(model_id))
if not validation["valid"]:
    raise RuntimeError(validation["issues"])

document = DirectorDocument.model_validate({
    "story_bible": {
        "project_theme": "The End - abstract music-reactive preview",
        "visual_style": "Sculptural liquid metal and translucent geometry; cyan, crimson and silver on black",
        "continuity_rules": ["Smooth connected motion", "No text or logos", "No rapid flashing"],
    },
    "scenes": [{
        "scene_id": "the-end-preview-01",
        "start_sample": "0",
        "end_sample": "384000",
        "intent": "Eight-second abstract music-reactive preview: liquid-metal ribbons and faceted translucent geometry transform in a dark spatial field. Restrained cyan, crimson and silver highlights. Expansion responds to bass, rotation to midrange, fine edge highlights to treble. No people, text, logos or strobing.",
        "camera": {"movement": "Slow continuous forward drift", "motion_strength": 0.35},
        "environment": {"location": "Abstract black spatial field"},
    }],
    "analysis_revision": 1,
})
response = requests.get(API, timeout=60)
response.raise_for_status()
project = response.json()["project"]
features = project["meta"].get("analysis", {}).get("features", {})
context = {
    "selected_range": {"start_sample": "0", "end_sample": "384000"},
    "sample_rate": 48000,
    "audio_features": {key: features.get(key) for key in ("duration_s", "bpm", "bpm_confidence")},
    "beats_s": [b for b in features.get("beats", []) if 0 <= float(b) <= 8],
    "note": "Tempo estimate has low confidence; prioritize energy and smooth modulation. Ignore ASR text.",
}
backend = LlamaCppDirectorBackend(
    model_root, device="cuda:1", gpu_layers="auto", vram_gb=48,
    executable=STUDIO / "tools" / "llama.cpp" / "llama-server.exe",
    context_length=8192, batch_size=64, ubatch_size=16, timeout_s=300,
)
try:
    print("Loading verified Qwen 8B GGUF on CUDA1", flush=True)
    backend.start()
    print("Generating abstract preview direction", flush=True)
    text = backend.generate(
        document,
        "Direct this abstract music-reactive eight-second scene. Keep the supplied scene ID and range. Describe smooth visible transformation and camera movement. Use the audio context as creative guidance, avoid claiming exact beat synchronization from generated video. No people, lettering, logos, flicker or strobing. Return the required JSON scene update.",
        timeline_context=context, max_tokens=1600,
    )
    result = validate_proposal(text, document)
    provenance = {"model_id": model_id, "device": backend.device, "runtime": "llama-server"}
finally:
    backend.close()

compiled = compile_scene(result.scenes[0], result.story_bible, "ltx_25")
artifact = {"document": result.model_dump(mode="json"), "provenance": provenance,
            "compiled": compiled, "audio_context": context}
(output / "director-preview.json").write_text(json.dumps(artifact, indent=2), encoding="utf-8")
current = requests.get(API, timeout=60)
current.raise_for_status()
revision = current.json()["project"]["revision"]
saved = requests.post(API + "/director/document", json={
    "expected_revision": revision, "document": result.model_dump(mode="json"),
}, timeout=120)
saved.raise_for_status()
print(json.dumps({"saved": True, "artifact": str(output / "director-preview.json"),
                  "provenance": provenance, "compiled": compiled}, indent=2), flush=True)
