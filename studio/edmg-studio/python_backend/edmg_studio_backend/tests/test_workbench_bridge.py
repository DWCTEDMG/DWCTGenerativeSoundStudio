from __future__ import annotations

from edmg_studio_backend.services.workbench_bridge import (
    build_unreal_bridge_export_payloads,
    build_unreal_bridge_preview,
    merge_reactive_lab_into_timeline,
    planner_lab_to_canonical_plan,
    planner_lab_to_project_analysis,
)


def test_planner_lab_conversion_builds_renderer_ready_analysis_and_plan():
    raw_analysis = {
        "basicInfo": {
            "fileName": "demo.wav",
            "durationSeconds": 48,
            "tempo": 124,
            "key": "F minor",
            "sampleRate": 48000,
            "channels": 2,
        },
        "themes": [{"theme": "future nostalgia"}],
        "visualImagery": [{"element": "neon skyline"}],
        "emotions": [{"emotion": "euphoria"}],
        "hookLine": "Neon skyline rising out of the chorus.",
        "narrativeStructure": "Lift into release",
        "energyCurve": [0.1, 0.45, 0.9],
        "spectralFeatures": {
            "brightness": 0.6,
            "warmth": 0.4,
            "dynamicRange": 0.7,
            "zeroCrossingRate": 0.12,
            "averageEnergy": 0.56,
            "motionBias": 0.62,
        },
    }
    raw_plan = {
        "executiveSummary": "Build a coherent neon-world arc.",
        "scenes": [
            {
                "id": 1,
                "title": "Cold open",
                "text": "Neon skyline with slow forward glide.",
                "negativePrompt": "muddy details",
                "approved": True,
                "status": "approved",
                "shotType": "wide",
                "transitionCue": "lift on downbeat",
                "continuityNote": "keep the same lead silhouette",
            },
            {
                "id": 2,
                "title": "Chorus release",
                "text": "Full color burst with stronger momentum.",
                "negativePrompt": "muddy details",
                "approved": False,
                "status": "draft",
            },
        ],
        "scenePlan": [
            {"id": 1, "startTime": "00:00", "endTime": "00:24"},
            {"id": 2, "startTime": "00:24", "endTime": "00:48"},
        ],
    }

    analysis = planner_lab_to_project_analysis(raw_analysis)
    plan = planner_lab_to_canonical_plan(raw_analysis, raw_plan, {"promptStyle": "cinematic"})

    assert analysis["features"]["duration_s"] == 48
    assert analysis["features"]["bpm"] == 124
    assert analysis["features"]["energy_curve"] == [0.1, 0.45, 0.9]
    assert analysis["transcript"]["text"].startswith("Neon skyline")
    assert "future nostalgia" in analysis["tags"]

    variant = plan["variants"][0]
    assert variant["name"] == "Planner Lab / cinematic"
    assert variant["scenes"][0]["start_s"] == 0.0
    assert variant["scenes"][0]["end_s"] == 24.0
    assert variant["scenes"][0]["prompt"] == "Neon skyline with slow forward glide."
    assert variant["scenes"][0]["negative_prompt"] == "muddy details"
    assert variant["scenes"][0]["approved"] is True


def test_reactive_lab_merge_upserts_motion_track_and_camera_keyframes():
    timeline = {
        "tracks": [
            {"id": "edmg_prompt", "type": "prompt", "clips": [{"id": "p1", "start_s": 0.0, "end_s": 8.0, "data": {"prompt": "keep"}}]},
            {"id": "edmg_motion", "type": "motion", "clips": [{"id": "old", "start_s": 0.0, "end_s": 8.0, "data": {"strength": 0.4}}]},
        ]
    }
    payload = {
        "metadata": {"fps": 12, "renderMode": "performance-led", "scheduleStride": 2},
        "sections": [{"id": 1, "startTime": 0.0, "endTime": 8.0, "label": "lift", "avgEnergy": 0.7, "approved": True, "renderMode": "performance-led"}],
        "cue_events": [{"id": 1, "frame": 24, "time": 2.0, "cueType": "push", "instruction": "accent"}],
        "repair_suggestions": [{"id": 1, "sectionId": 1, "issue": "tighten", "action": "reduce shake"}],
        "schedules": {
            "zoom": "0:(1.0000), 48:(1.2200)",
            "rotation_y": "0:(0.0000), 48:(8.0000)",
            "rotation_z": "0:(0.0000), 48:(5.0000)",
            "translation_z": "0:(0.0000), 48:(-16.0000)",
            "strength": "0:(0.3600), 48:(0.5200)",
            "cfg_scale": "0:(6.5000), 48:(7.5000)",
            "brightness": "0:(0.5000), 48:(0.6400)",
        },
        "handoff_manifest": {"approvedSectionIds": [1], "renderMode": "performance-led", "scheduleStride": 2},
    }

    merged = merge_reactive_lab_into_timeline(timeline, payload)

    prompt_track = next(track for track in merged["tracks"] if track["type"] == "prompt")
    motion_track = next(track for track in merged["tracks"] if track["type"] == "motion")
    motion_data = motion_track["clips"][0]["data"]

    assert prompt_track["clips"][0]["data"]["prompt"] == "keep"
    assert motion_data["strength_schedule"] == "0:(0.3600), 48:(0.5200)"
    assert motion_data["cfg_scale_schedule"] == "0:(6.5000), 48:(7.5000)"
    assert motion_data["zoom_schedule"] == "0:(1.0000), 48:(1.2200)"
    assert merged["render"]["fps_output"] == 12
    assert merged["camera"]["keyframes"][0]["zoom"] == 1.0
    assert merged["camera"]["keyframes"][-1]["rotation_deg"] == 5.0
    assert merged["reactive_lab"]["handoff_manifest"]["approvedSectionIds"] == [1]


def test_unreal_bridge_preview_builds_export_handoff_and_live_control_shapes():
    analysis = {
        "features": {
            "duration_s": 8.0,
            "bpm": 124,
            "beat_times": [0.0, 0.5, 1.0, 1.5],
        },
        "audio_path": "projects/demo/assets/audio/source.wav",
    }
    plan = {
        "variants": [
            {
                "duration_s": 8.0,
                "scenes": [
                    {
                        "id": "scene-1",
                        "name": "Intro push",
                        "start_s": 0.0,
                        "end_s": 4.0,
                        "prompt": "Lead silhouette pushing through a neon haze.",
                        "negative_prompt": "muddy lighting",
                        "continuity_note": "keep the same lead silhouette",
                        "shot_type": "tracking push-in",
                        "approved": True,
                    },
                    {
                        "id": "scene-2",
                        "name": "Chorus hit",
                        "start_s": 4.0,
                        "end_s": 8.0,
                        "prompt": "Color burst as the chorus lands.",
                    },
                ],
            }
        ]
    }
    timeline = {
        "render": {"fps_output": 24},
        "camera": {
            "keyframes": [
                {"t": 0.0, "zoom": 1.0},
                {"t": 4.0, "zoom": 1.2},
            ]
        },
        "reactive_lab": {
            "metadata": {"renderMode": "performance-led", "scheduleStride": 2},
            "sections": [
                {"id": "scene-1", "label": "Intro", "startTime": 0.0, "avgEnergy": 0.35, "approved": True},
                {"id": "scene-2", "label": "Chorus", "startTime": 4.0, "avgEnergy": 0.8, "approved": False},
            ],
            "cue_events": [
                {"id": "cue-1", "frame": 48, "time": 2.0, "cueType": "impact", "instruction": "accent the downbeat"}
            ],
            "repair_suggestions": [
                {"sectionId": "scene-2", "issue": "face drift", "action": "reuse anchor seed"}
            ],
            "handoff_manifest": {"approvedSectionIds": ["scene-1"], "renderMode": "performance-led", "scheduleStride": 2},
        },
    }

    preview = build_unreal_bridge_preview(
        project_id="demo-project",
        project_name="Demo Project",
        analysis=analysis,
        plan=plan,
        timeline=timeline,
        variant_index=0,
    )

    assert preview["shot_metadata_export"]["sequence_name"] == "demo_project_MainSequence"
    assert preview["shot_metadata_export"]["shots"][0]["start_frame"] == 0
    assert preview["shot_metadata_export"]["shots"][1]["end_frame"] == 192
    assert preview["render_handoff"]["render_mode"] == "performance-led"
    assert preview["render_handoff"]["sections"][0]["engine_hint"] == "comfyui_motion"
    assert preview["render_handoff"]["sections"][1]["repair_actions"] == ["reuse anchor seed"]
    assert preview["live_control_bridge"]["transports"]["osc"] == ["/edmg/section", "/edmg/beat", "/edmg/camera"]
    assert preview["live_control_bridge"]["cue_events"][0]["cue_type"] == "impact"
    assert preview["live_control_bridge"]["camera_keyframes"][-1]["zoom"] == 1.2


def test_unreal_bridge_export_payloads_build_expected_bundle_files():
    preview = build_unreal_bridge_preview(
        project_id="demo-project",
        project_name="Demo Project",
        analysis={
            "features": {
                "duration_s": 8.0,
                "bpm": 124,
                "beat_times": [0.0, 0.5, 1.0],
                "energy_curve": [0.1, 0.4, 0.8],
                "musical_key": "F minor",
            },
            "transcript": {"text": "Neon skyline rising into the chorus."},
            "tags": ["future nostalgia", "neon skyline"],
        },
        plan={
            "variants": [
                {
                    "duration_s": 8.0,
                    "scenes": [
                        {"id": "scene-1", "name": "Intro", "start_s": 0.0, "end_s": 4.0, "prompt": "Intro prompt", "approved": True},
                        {"id": "scene-2", "name": "Chorus", "start_s": 4.0, "end_s": 8.0, "prompt": "Chorus prompt"},
                    ],
                }
            ]
        },
        timeline={
            "render": {"fps_output": 24},
            "reactive_lab": {
                "metadata": {"renderMode": "performance-led"},
                "cue_events": [{"id": "cue-1", "frame": 24, "time": 1.0, "cueType": "impact"}],
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
        created_at="2026-05-05 13:30:00",
    )

    assert sorted(payloads.keys()) == [
        "audio_markers.json",
        "bundle_manifest.json",
        "live_control_bridge.json",
        "render_handoff.json",
        "return_contract.json",
        "shot_manifest.json",
        "style_packet.json",
    ]
    assert payloads["audio_markers.json"]["sequence_name"] == "demo_project_MainSequence"
    assert payloads["style_packet.json"]["visual_dna"]["identity"]["core_themes"] == ["future nostalgia"]
    assert payloads["return_contract.json"]["assembly_mode"] == "ffmpeg_back_in_studio"
    assert payloads["bundle_manifest.json"]["files"][0]["path"] == "shot_manifest.json"
