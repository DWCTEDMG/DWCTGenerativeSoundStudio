from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from edmg_studio_backend.services.unreal_bridge_consumer import (
    build_unreal_sequence_import_plan,
    load_unreal_bridge_bundle,
    write_unreal_sequence_import_plan,
)
from edmg_studio_backend.services.workbench_bridge import (
    build_unreal_bridge_export_payloads,
    build_unreal_bridge_preview,
)


def _write_bundle(tmp_path: Path) -> Path:
    preview = build_unreal_bridge_preview(
        project_id="demo-project",
        project_name="Demo Project",
        analysis={
            "basicInfo": {"durationSeconds": 8.0},
            "features": {"bpm": 124},
            "audio": {"filename": "demo.wav"},
        },
        plan={
            "variants": [
                {
                    "duration_s": 8.0,
                    "scenes": [
                        {
                            "id": "scene-1",
                            "name": "Intro",
                            "start_s": 0.0,
                            "end_s": 4.0,
                            "prompt": "Intro prompt",
                            "continuity_note": "preserve skyline silhouette",
                            "shot_type": "wide",
                            "approved": True,
                        },
                        {
                            "id": "scene-2",
                            "name": "Chorus",
                            "start_s": 4.0,
                            "end_s": 8.0,
                            "prompt": "Chorus prompt",
                            "shot_type": "push-in",
                        },
                    ],
                }
            ]
        },
        timeline={
            "render": {"fps_output": 24},
            "reactive_lab": {
                "metadata": {"renderMode": "performance-led"},
                "sections": [{"id": "chorus", "label": "chorus", "startTime": 4.0, "approved": True}],
                "cue_events": [
                    {
                        "id": "cue-1",
                        "frame": 36,
                        "time": 1.5,
                        "cueType": "impact",
                        "instruction": "flash hit",
                    }
                ],
            },
            "camera": {
                "keyframes": [
                    {"frame": 0, "zoom": 1.0},
                    {"frame": 96, "zoom": 1.15},
                ]
            },
        },
        variant_index=0,
    )
    payloads = build_unreal_bridge_export_payloads(
        project_id="demo-project",
        project_name="Demo Project",
        variant_index=0,
        preview=preview,
        analysis={
            "features": {
                "bpm": 124,
                "musical_key": "F minor",
                "energy_curve": [0.1, 0.4, 0.8],
            },
            "transcript": {"text": "Neon skyline rising into the chorus."},
            "tags": ["future nostalgia", "neon skyline"],
        },
        visual_dna={
            "identity": {"core_themes": ["future nostalgia"]},
            "continuity": {"subject_anchors": ["lead silhouette"]},
            "prompt_guidance": {"positive_fragments": ["cinematic neon haze"]},
        },
        created_at="2026-05-05 18:00:00",
    )
    bundle_dir = tmp_path / "demo_bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    for filename, payload in payloads.items():
        (bundle_dir / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return bundle_dir


def test_build_unreal_sequence_import_plan_reads_bundle_contract(tmp_path):
    bundle_dir = _write_bundle(tmp_path)

    bundle = load_unreal_bridge_bundle(bundle_dir)
    assert bundle["manifest"]["export_family"] == "unreal_bridge_bundle"
    assert bundle["return_contract"]["unreal_consumer"]["default_return_dir"] == "returned"

    plan = build_unreal_sequence_import_plan(bundle_dir)
    assert plan.sequence_name == "demo_project_MainSequence"
    assert plan.asset_path == "/Game/EDMG/Sequences/demo_project_MainSequence"
    assert plan.expected_return_dir.endswith("demo_bundle\\returned") or plan.expected_return_dir.endswith("demo_bundle/returned")
    assert plan.expected_outputs == ["shot_render.mov", "alpha_pass.mov", "metadata.json"]
    assert len(plan.shots) == 2
    assert plan.shots[0].camera_name == "shot_001_scene_1_Cam"
    assert any(marker.source == "cue_event" and marker.label == "flash hit" for marker in plan.markers)
    assert plan.playback_end >= 192


def test_write_unreal_sequence_import_plan_persists_json(tmp_path):
    bundle_dir = _write_bundle(tmp_path)
    plan = build_unreal_sequence_import_plan(bundle_dir, content_path="/Game/Cinematics/EDMG", asset_name="DemoSequence")
    out_path = write_unreal_sequence_import_plan(plan, tmp_path / "plan.json")
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["asset_path"] == "/Game/Cinematics/EDMG/DemoSequence"
    assert payload["shots"][0]["shot_id"] == "shot_001_scene_1"
    assert payload["markers"][0]["label"] == "Intro"


def test_unreal_import_tool_supports_dry_run(tmp_path):
    bundle_dir = _write_bundle(tmp_path)
    script_path = (
        Path(__file__).resolve().parents[3]
        / "tools"
        / "unreal"
        / "import_unreal_bridge_bundle.py"
    )
    spec = importlib.util.spec_from_file_location("edmg_unreal_import_tool", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    report = module.run_import(
        bundle_dir,
        dry_run=True,
        plan_json=str(tmp_path / "tool_plan.json"),
    )
    assert report["ok"] is True
    assert report["mode"] == "dry_run"
    assert report["asset_path"] == "/Game/EDMG/Sequences/demo_project_MainSequence"
    assert Path(report["report_path"]).exists()
    assert Path(report["return_dir"]).exists()
