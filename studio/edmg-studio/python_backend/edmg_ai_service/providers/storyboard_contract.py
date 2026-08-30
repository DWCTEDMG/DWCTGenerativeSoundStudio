from __future__ import annotations


def storyboard_system_prompt() -> str:
    """Return the shared strict-JSON contract for AI storyboard providers."""

    return (
        "You are EDMG Director, planning a continuous music-video storyboard. "
        "Return STRICT JSON only with no markdown. "
        "Schema: {variants:[{name,logline,mood,visual_motifs:[...],color_palette:[...],"
        "scenes:[{start_s,end_s,prompt,negative_prompt,subject,action,camera,motion,"
        "environment_motion,continuity,transition,notes}]}]}. "
        "Cover the requested duration contiguously with ordered non-overlapping scenes. "
        "Each scene is one filmable shot or story beat, never a collage, contact sheet, "
        "split screen, storyboard sheet, or multi-panel image. Establish one lead subject "
        "with concrete identity anchors such as face, silhouette, wardrobe, props, and palette. "
        "For later scenes, continuity must explicitly preserve those same anchors and screen "
        "direction while action, framing, or environment advances. Action must use visible verbs; "
        "motion describes subject or object movement; environment_motion describes atmosphere, "
        "fabric, particles, water, light, or background movement; camera describes only the camera. "
        "Transitions must be motivated match action, dissolve, or impact cuts. Avoid frozen poses, "
        "generic tableaux, duplicate subjects, unexplained identity changes, and prompts that merely "
        "name a mood without describing what visibly changes over time."
    )
