"""AI auto-configuration for animation / motion rendering.

This module turns a single user choice (an "animation preset" button such as
*Low quality*, *High quality full motion*, *Cinematic 3D*, *Animate image*) plus a
render engine choice (internal renderer or ComfyUI) into a fully-formed render
configuration: render settings, a Deforum motion schedule (2D + the full 3D
camera model), and the request payloads needed to launch the job.

The logic here is intentionally pure and hardware-agnostic so it can be unit
tested without a GPU. The FastAPI layer supplies the hardware tier defaults
(from ``_build_internal_render_plan``) and is responsible for actually launching
jobs. Manual configuration endpoints remain untouched; this is an additive
"push a button and the AI sets the settings, then renders" layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Mapping from internal motion-schedule keys to the InternalVideoRenderRequest
# ``deforum_*`` override field names.
_SCHEDULE_TO_REQUEST = {
    "zoom": "deforum_zoom",
    "angle": "deforum_angle",
    "translation_x": "deforum_translation_x",
    "translation_y": "deforum_translation_y",
    "translation_z": "deforum_translation_z",
    "rotation_3d_x": "deforum_rotation_3d_x",
    "rotation_3d_y": "deforum_rotation_3d_y",
    "rotation_3d_z": "deforum_rotation_3d_z",
    "fov": "deforum_fov",
}


@dataclass(frozen=True)
class MotionProfile:
    """Amplitudes for a motion intensity level.

    ``label`` is human readable. The amplitude fields describe the maximum
    excursion applied across the clip. 3D fields are only emitted when non-zero.
    """

    name: str
    label: str
    zoom_end: float = 1.0
    angle_amp: float = 0.0
    pan_x_amp: float = 0.0
    pan_y_amp: float = 0.0
    translation_z_end: float = 0.0
    rotation_3d_x_end: float = 0.0
    rotation_3d_y_amp: float = 0.0
    fov: float | None = None

    @property
    def is_3d(self) -> bool:
        return bool(self.translation_z_end or self.rotation_3d_x_end or self.rotation_3d_y_amp)


MOTION_PROFILES: dict[str, MotionProfile] = {
    "none": MotionProfile("none", "Still (no camera motion)"),
    "subtle": MotionProfile(
        "subtle", "Subtle / partial motion", zoom_end=1.04, pan_x_amp=10.0, pan_y_amp=6.0
    ),
    "moderate": MotionProfile(
        "moderate", "Moderate motion", zoom_end=1.08, angle_amp=2.0, pan_x_amp=22.0, pan_y_amp=14.0
    ),
    "full": MotionProfile(
        "full", "Full 2D motion", zoom_end=1.12, angle_amp=4.0, pan_x_amp=42.0, pan_y_amp=26.0
    ),
    "full_3d": MotionProfile(
        "full_3d",
        "Full 3D camera motion",
        zoom_end=1.06,
        angle_amp=2.0,
        pan_x_amp=18.0,
        pan_y_amp=10.0,
        translation_z_end=140.0,
        rotation_3d_x_end=8.0,
        rotation_3d_y_amp=22.0,
        fov=70.0,
    ),
}


@dataclass(frozen=True)
class AnimationPreset:
    """A one-click animation preset (the "buttons")."""

    id: str
    label: str
    description: str
    quality: str  # draft | balanced | quality
    motion: str  # key into MOTION_PROFILES
    temporal_mode: str  # off | keyframes | frame_img2img | video_model
    motion_strategy: str = "manual"  # manual | storyboard_full_motion
    scene_motion: str = "subject"  # camera | subject | scene
    engine_hint: str = "auto"  # auto | internal | comfyui
    comfyui_engine: str = "animatediff"  # animatediff | svd | regional
    uses_source_image: bool = False
    source_strength: float = 0.55
    # camera = move the whole image; layered modes animate individual objects.
    animation_mode: str = "camera"  # camera | parallax | masked | segment | background
    requires_masks: bool = False

    @property
    def is_layered(self) -> bool:
        return self.animation_mode in {"parallax", "masked", "segment", "background"}

    def to_public(self) -> dict[str, Any]:
        profile = MOTION_PROFILES.get(self.motion, MOTION_PROFILES["none"])
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "quality": self.quality,
            "motion": self.motion,
            "motion_label": profile.label,
            "is_3d": profile.is_3d,
            "temporal_mode": self.temporal_mode,
            "motion_strategy": self.motion_strategy,
            "scene_motion": self.scene_motion,
            "engine_hint": self.engine_hint,
            "comfyui_engine": self.comfyui_engine,
            "uses_source_image": self.uses_source_image,
            "animation_mode": self.animation_mode,
            "animates_objects": self.is_layered,
            "requires_masks": self.requires_masks,
        }


# The curated preset list shown as buttons in the UI.
ANIMATION_PRESETS: list[AnimationPreset] = [
    AnimationPreset(
        id="draft_fast",
        label="Draft / Fast preview",
        description="Low quality, quick render with subtle motion. Best for previews.",
        quality="draft",
        motion="subtle",
        temporal_mode="keyframes",
    ),
    AnimationPreset(
        id="subtle_motion",
        label="High quality, subtle motion",
        description="High quality render with gentle, partial motion.",
        quality="quality",
        motion="subtle",
        temporal_mode="keyframes",
    ),
    AnimationPreset(
        id="balanced_motion",
        label="Balanced motion",
        description="Balanced quality and moderate 2D camera motion.",
        quality="balanced",
        motion="moderate",
        temporal_mode="frame_img2img",
    ),
    AnimationPreset(
        id="full_motion",
        label="High quality, full motion",
        description="Storyboard-driven full motion using generated keyframe anchors and internal video-model shots.",
        quality="quality",
        motion="full",
        temporal_mode="video_model",
        motion_strategy="storyboard_full_motion",
        scene_motion="scene",
    ),
    AnimationPreset(
        id="cinematic_3d",
        label="Cinematic full 3D motion",
        description="High quality render using the full 3D camera engine (dolly, yaw, pitch).",
        quality="quality",
        motion="full_3d",
        temporal_mode="frame_img2img",
    ),
    AnimationPreset(
        id="image_animation",
        label="Animate an image",
        description="Bring an uploaded image (painting or photo) to life with 3D motion and prompts.",
        quality="balanced",
        motion="full_3d",
        temporal_mode="frame_img2img",
        uses_source_image=True,
        source_strength=0.5,
    ),
    AnimationPreset(
        id="comfyui_animatediff",
        label="ComfyUI AnimateDiff (full workflow)",
        description="Run the whole animation workflow on ComfyUI with AnimateDiff.",
        quality="balanced",
        motion="moderate",
        temporal_mode="frame_img2img",
        engine_hint="comfyui",
        comfyui_engine="animatediff",
    ),
    AnimationPreset(
        id="comfyui_svd",
        label="ComfyUI Stable Video Diffusion (full workflow)",
        description="Run the whole animation workflow on ComfyUI with SVD image-to-video.",
        quality="balanced",
        motion="moderate",
        temporal_mode="frame_img2img",
        engine_hint="comfyui",
        comfyui_engine="svd",
        uses_source_image=True,
    ),
    # --- Object / layer animation (animate individual objects within an image) ---
    AnimationPreset(
        id="parallax_animation",
        label="Parallax (2.5D) animation",
        description="Split an image into depth layers so near and far regions move by different amounts.",
        quality="balanced",
        motion="full_3d",
        temporal_mode="frame_img2img",
        uses_source_image=True,
        animation_mode="parallax",
    ),
    AnimationPreset(
        id="animate_subject",
        label="Animate the subject",
        description="Auto-detect the main subject and animate it over a near-static background.",
        quality="balanced",
        motion="full_3d",
        temporal_mode="frame_img2img",
        uses_source_image=True,
        animation_mode="segment",
    ),
    AnimationPreset(
        id="parallax_background",
        label="Parallax background",
        description="Auto-detect the subject and parallax the background behind it.",
        quality="balanced",
        motion="full_3d",
        temporal_mode="frame_img2img",
        uses_source_image=True,
        animation_mode="background",
    ),
    AnimationPreset(
        id="masked_object_motion",
        label="Animate masked objects",
        description="Animate one or more masked objects independently over a held background.",
        quality="balanced",
        motion="full_3d",
        temporal_mode="frame_img2img",
        uses_source_image=True,
        animation_mode="masked",
        requires_masks=True,
    ),
    AnimationPreset(
        id="comfyui_regional_motion",
        label="ComfyUI regional motion (per-object prompts)",
        description="Drive per-object motion on ComfyUI with masked regional prompts (AnimateDiff).",
        quality="balanced",
        motion="moderate",
        temporal_mode="frame_img2img",
        engine_hint="comfyui",
        comfyui_engine="regional",
        uses_source_image=True,
        animation_mode="masked",
        requires_masks=True,
    ),
]

ANIMATION_PRESETS_BY_ID: dict[str, AnimationPreset] = {p.id: p for p in ANIMATION_PRESETS}


def list_presets() -> list[dict[str, Any]]:
    return [p.to_public() for p in ANIMATION_PRESETS]


def resolve_preset(preset_id: str | None) -> AnimationPreset | None:
    return ANIMATION_PRESETS_BY_ID.get(str(preset_id or "").strip())


def _fmt_schedule(*pairs: tuple[int, float]) -> str:
    return ", ".join(f"{int(f)}:({round(float(v), 4)})" for f, v in pairs)


def build_motion_schedule(profile: MotionProfile | str, *, duration_s: float, fps: int) -> dict[str, str]:
    """Build Deforum-style schedule strings for a motion profile.

    Schedules are keyed by motion-schedule names (zoom/angle/translation_*/...),
    not request field names. 3D keys are only present for 3D profiles.
    """
    prof = MOTION_PROFILES.get(profile, MOTION_PROFILES["none"]) if isinstance(profile, str) else profile
    fps = max(1, int(fps))
    end = max(1, int(round(float(max(0.0, duration_s)) * fps)))
    mid = max(1, end // 2)
    schedule: dict[str, str] = {}

    if prof.name == "none":
        return schedule

    if abs(prof.zoom_end - 1.0) > 1e-6:
        schedule["zoom"] = _fmt_schedule((0, 1.0), (end, prof.zoom_end))
    if prof.angle_amp:
        schedule["angle"] = _fmt_schedule((0, 0.0), (mid, prof.angle_amp), (end, -prof.angle_amp))
    if prof.pan_x_amp:
        schedule["translation_x"] = _fmt_schedule((0, 0.0), (mid, prof.pan_x_amp), (end, 0.0))
    if prof.pan_y_amp:
        schedule["translation_y"] = _fmt_schedule((0, 0.0), (mid, prof.pan_y_amp), (end, -prof.pan_y_amp))

    if prof.is_3d:
        if prof.translation_z_end:
            schedule["translation_z"] = _fmt_schedule((0, 0.0), (end, prof.translation_z_end))
        if prof.rotation_3d_x_end:
            schedule["rotation_3d_x"] = _fmt_schedule((0, 0.0), (end, prof.rotation_3d_x_end))
        if prof.rotation_3d_y_amp:
            schedule["rotation_3d_y"] = _fmt_schedule(
                (0, 0.0), (mid, prof.rotation_3d_y_amp), (end, -prof.rotation_3d_y_amp)
            )
        if prof.fov:
            schedule["fov"] = _fmt_schedule((0, float(prof.fov)))

    return schedule


def schedule_to_request_overrides(schedule: dict[str, str]) -> dict[str, str]:
    """Map motion-schedule keys to InternalVideoRenderRequest ``deforum_*`` fields."""
    return {
        _SCHEDULE_TO_REQUEST[key]: value
        for key, value in schedule.items()
        if key in _SCHEDULE_TO_REQUEST
    }


def _quality_to_requested_tier(quality: str) -> str:
    q = str(quality or "").lower().strip()
    if q in {"draft", "balanced", "quality"}:
        return q
    return "auto"


@dataclass(frozen=True)
class AutoConfig:
    preset_id: str
    engine: str  # internal | comfyui
    requested_tier: str
    motion_profile: str
    motion_schedule: dict[str, str]
    internal_request: dict[str, Any]
    comfyui_request: dict[str, Any] | None
    uses_source_image: bool
    animation_mode: str = "camera"
    layered_request: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)

    def to_public(self) -> dict[str, Any]:
        return {
            "preset_id": self.preset_id,
            "engine": self.engine,
            "requested_tier": self.requested_tier,
            "motion_profile": self.motion_profile,
            "motion_schedule": self.motion_schedule,
            "internal_request": self.internal_request,
            "comfyui_request": self.comfyui_request,
            "uses_source_image": self.uses_source_image,
            "animation_mode": self.animation_mode,
            "layered_request": self.layered_request,
            "notes": self.notes,
        }


def resolve_engine(preset: AnimationPreset, requested_engine: str, *, comfyui_available: bool) -> str:
    """Decide which renderer to use.

    - explicit "internal"/"comfyui" is honored (comfyui downgrades to internal
      only if unavailable),
    - "auto" follows the preset hint, falling back to internal when ComfyUI is
      not reachable.
    """
    req = str(requested_engine or "auto").lower().strip()
    if req == "internal":
        return "internal"
    if req == "comfyui":
        return "comfyui" if comfyui_available else "internal"
    # auto -> preset hint
    hint = str(preset.engine_hint or "auto").lower().strip()
    if hint == "comfyui":
        return "comfyui" if comfyui_available else "internal"
    return "internal"


def build_autoconfig(
    preset: AnimationPreset,
    *,
    engine: str = "auto",
    tier_defaults: dict[str, Any],
    applied_tier: str,
    preferred_model: str = "auto",
    device_preference: str = "auto",
    duration_s: float = 10.0,
    fps: int = 24,
    variant_index: int = 0,
    source_asset: str | None = None,
    comfyui_available: bool = False,
    tensorrt_sd15_available: bool = False,
) -> AutoConfig:
    """Produce a complete render configuration for a preset + engine choice."""
    notes: list[str] = []
    resolved_engine = resolve_engine(preset, engine, comfyui_available=comfyui_available)
    if str(engine).lower().strip() == "comfyui" and resolved_engine == "internal":
        notes.append("ComfyUI not reachable; using the internal renderer instead.")

    profile = MOTION_PROFILES.get(preset.motion, MOTION_PROFILES["none"])
    schedule = build_motion_schedule(profile, duration_s=duration_s, fps=fps)
    if profile.is_3d:
        notes.append("Full 3D camera motion enabled (dolly + yaw/pitch).")

    td = dict(tier_defaults or {})
    fps_output = int(td.get("fps_output", fps or 24))
    fps_render = int(td.get("fps_render", 2))

    use_source = bool(preset.uses_source_image and source_asset)
    if preset.uses_source_image and not source_asset:
        notes.append("This preset animates an uploaded image, but no source image was provided.")

    internal_request: dict[str, Any] = {
        "variant_index": int(variant_index),
        "fps_output": fps_output,
        "fps_render": fps_render,
        "width": int(td.get("width", 768)),
        "height": int(td.get("height", 432)),
        "steps": int(td.get("steps", 15)),
        "cfg": float(td.get("cfg", 7.0)),
        "keyframe_interval_s": float(td.get("keyframe_interval_s", 5.0)),
        "interpolation_engine": str(td.get("interpolation_engine", "auto")),
        "model_id": str(preferred_model or "auto"),
        "render_mode": "auto",
        "render_tier": str(applied_tier or "auto"),
        "device_preference": str(device_preference or "auto"),
        "temporal_mode": str(preset.temporal_mode or td.get("temporal_mode", "keyframes")),
        "motion_strategy": str(preset.motion_strategy or "manual"),
        "temporal_steps": int(td.get("temporal_steps", 12)),
        "refine_every_n_frames": int(td.get("refine_every_n_frames", 1)),
        "anchor_strength": float(td.get("anchor_strength", 0.20)),
        "prompt_blend": bool(td.get("prompt_blend", True)),
        "allow_hosted_fallback": True,
    }
    if preset.motion_strategy == "storyboard_full_motion":
        storyboard_request = {
            "video_model_engine": "auto",
            "video_model_motion_score_mode": "auto",
            "video_model_anchor_mode": "both",
            "video_model_prompt_refine": True,
            "video_model_scene_motion": str(preset.scene_motion or "subject"),
            "video_model_apply_timeline_camera": True,
            "video_model_noise_aug_strength": max(float(td.get("video_model_noise_aug_strength", 0.02)), 0.06),
        }
        if tensorrt_sd15_available:
            storyboard_request.update(
                {
                    "video_model_keyframe_renderer": "tensorrt_sd15",
                    "video_model_keyframe_model_id": "local_sd15_tensorrt_bundle",
                }
            )
        internal_request.update(storyboard_request)
        notes.append(
            "Storyboard full motion enabled: Studio generates keyframe anchors from the plan, then renders short internal video-model shots with subject and scene motion prompts."
        )
        if tensorrt_sd15_available:
            notes.append(
                "TensorRT SD1.5 storyboard anchors enabled: TensorRT generates the prompt-derived keyframes quickly, while SVD or AnimateDiff remains the motion engine."
            )
    internal_request.update(schedule_to_request_overrides(schedule))
    if use_source:
        internal_request["source_asset"] = str(source_asset)
        internal_request["source_strength"] = float(preset.source_strength)

    comfyui_request: dict[str, Any] | None = None
    if resolved_engine == "comfyui":
        comfyui_request = {
            "variant_index": int(variant_index),
            "engine": str(preset.comfyui_engine or "animatediff"),
            "width": int(td.get("width", 768)),
            "height": int(td.get("height", 432)),
            "steps": int(td.get("steps", 20)),
            "cfg": float(td.get("cfg", 6.5)),
            "fps": fps_output,
        }
        if use_source:
            comfyui_request["source_asset"] = str(source_asset)

    layered_request: dict[str, Any] | None = None
    if preset.is_layered:
        layered_request = {
            "source_asset": str(source_asset) if source_asset else None,
            "mode": preset.animation_mode,
            "motion": preset.motion,
            "fps": fps_output,
            "duration_s": float(duration_s),
            "width": int(td.get("width", 768)),
            "height": int(td.get("height", 432)),
        }
        if preset.requires_masks:
            notes.append("This preset animates masked objects; provide one or more masks.")

    return AutoConfig(
        preset_id=preset.id,
        engine=resolved_engine,
        requested_tier=_quality_to_requested_tier(preset.quality),
        motion_profile=preset.motion,
        motion_schedule=schedule,
        internal_request=internal_request,
        comfyui_request=comfyui_request,
        uses_source_image=use_source,
        animation_mode=preset.animation_mode,
        layered_request=layered_request,
        notes=notes,
    )
