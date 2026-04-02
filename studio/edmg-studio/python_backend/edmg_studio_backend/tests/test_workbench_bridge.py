from __future__ import annotations

from edmg_studio_backend.services.workbench_bridge import (
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
