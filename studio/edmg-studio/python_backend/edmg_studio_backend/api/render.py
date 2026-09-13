from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from ..errors import UserFacingError
from ..revisions import RevisionRoute
from ..schemas import (
    AutoAnimateRequest,
    GenerationRequest,
    InternalVideoRenderRequest,
    LayeredAnimateRequest,
    ParseqMotionApplyRequest,
    PerformerWorkflowPlanRequest,
    PerformerWorkflowRunRequest,
    RenderConductorPlanRequest,
    RenderConductorPromoteRequest,
    RenderMotionRequest,
    RenderScenesRequest,
    TensorRTStandaloneRenderRequest,
)


@dataclass(frozen=True)
class RenderRouterDependencies:
    resolve: Callable[[str], Any]


def create_render_router(deps: RenderRouterDependencies) -> APIRouter:
    router = APIRouter(route_class=RevisionRoute)
    @router.post("/v1/projects/{project_id}/render/cosmos/scene")
    def render_cosmos_scene(project_id: str, payload: dict[str, Any]):
        """Generate a single video clip for one scene using NVIDIA Cosmos.

        Uses your existing NVIDIA API key (same as Nemotron Ultra).
        Returns a base path-relative video path once the clip is saved.

        payload fields (all optional):
          scene_index   : int   (default 0)
          variant_index : int   (default 0)
          model         : str   "text2world" | "video2world" | "cosmos3"
          seed          : int
          steps         : int
          guidance_scale: float
          num_frames    : int
          fps           : float
          use_keyframe  : bool  if true and variant has a rendered keyframe,
                                passes it as the init image for video2world
        """
        _cosmos_client = deps.resolve("_cosmos_client")
        _hardware_profile = deps.resolve("_hardware_profile")
        _render_provider_status = deps.resolve("_render_provider_status")
        render_settings = deps.resolve("render_settings")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")

        provider_status = _render_provider_status()
        cosmos_status = provider_status.get("cosmos") or {}
        if not cosmos_status.get("configured"):
            raise UserFacingError(
                "Cosmos NIM is not configured.",
                hint=(
                    "Cosmos video generation runs on a self-hosted NVIDIA NIM (there is no hosted Cosmos "
                    "video endpoint). Start a Cosmos NIM on a CUDA GPU and set its URL in "
                    "Settings → GPU / Render Runtime → Cosmos (Base URL), e.g. http://127.0.0.1:8000."
                ),
                code="COSMOS_NOT_CONFIGURED",
                status_code=400,
            )

        plan = proj.meta.get("last_plan")
        if not plan or not (plan.get("variants") or []):
            raise HTTPException(400, "No plan generated — run Plan first.")

        variant_index = int((payload or {}).get("variant_index") or 0)
        variants = plan["variants"]
        if variant_index < 0 or variant_index >= len(variants):
            raise HTTPException(400, "variant_index out of range")

        variant = variants[variant_index]
        scenes = variant.get("scenes") or []
        scene_index = int((payload or {}).get("scene_index") or 0)
        if scene_index < 0 or scene_index >= len(scenes):
            raise HTTPException(400, f"scene_index {scene_index} out of range (0–{len(scenes)-1})")

        scene = scenes[scene_index]
        project_dir = store.project_dir(project_id)
        cosmos_cfg = dict(render_settings.get().get("cosmos") or {})
        client = _cosmos_client()

        prompt = str(scene.get("prompt") or "cinematic music video").strip()
        negative = str(scene.get("negative_prompt") or "blurry, low quality, text, watermark, logo").strip()
        model = str((payload or {}).get("model") or cosmos_cfg.get("model") or "cosmos3")
        steps = int((payload or {}).get("steps") or cosmos_cfg.get("steps") or 50)
        guidance_scale = float((payload or {}).get("guidance_scale") or cosmos_cfg.get("guidance_scale") or 7.5)
        num_frames = int((payload or {}).get("num_frames") or cosmos_cfg.get("num_frames") or 121)
        fps = float((payload or {}).get("fps") or cosmos_cfg.get("fps") or 24.0)
        seed = (payload or {}).get("seed")
        prompt_upsampling = bool(cosmos_cfg.get("prompt_upsampling", True))

        out_dir = project_dir / "cosmos" / f"variant_{variant_index}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"scene_{scene_index:04d}.mp4"

        use_keyframe = bool((payload or {}).get("use_keyframe", False))
        init_image = None
        if use_keyframe or model in ("video2world",):
            kf_path = project_dir / "stills" / f"variant_{variant_index}" / f"scene_{scene_index:04d}.png"
            if kf_path.exists():
                try:
                    from PIL import Image as PILImage
                    init_image = PILImage.open(str(kf_path)).convert("RGB")
                except Exception:
                    init_image = None

        hw = _hardware_profile()
        width = int(hw.get("preferred_width") or 1280)
        height = int(hw.get("preferred_height") or 704)

        if init_image is not None and model in ("video2world", "cosmos3"):
            result = client.image_to_video(
                image=init_image,
                out_path=out_path,
                prompt=prompt,
                negative_prompt=negative,
                width=width,
                height=height,
                fps=fps,
                num_frames=num_frames,
                steps=steps,
                guidance_scale=guidance_scale,
                seed=int(seed) if seed is not None else None,
                model=model,
            )
        else:
            result = client.text_to_video(
                prompt=prompt,
                out_path=out_path,
                negative_prompt=negative,
                width=width,
                height=height,
                fps=fps,
                num_frames=num_frames,
                steps=steps,
                guidance_scale=guidance_scale,
                seed=int(seed) if seed is not None else None,
                prompt_upsampling=prompt_upsampling,
                model=model,
            )

        rel = result.video_path.relative_to(project_dir).as_posix()
        return {
            "ok": True,
            "provider": "nvidia-cosmos",
            "video": rel,
            "video_abs": str(result.video_path),
            "scene_index": scene_index,
            "model": result.model,
            "duration_s": result.duration_s,
            "frames": result.frames,
            "fps": result.fps,
            "seed": result.seed,
        }

    @router.post("/v1/projects/{project_id}/render/cosmos/all_scenes")
    def render_cosmos_all_scenes(project_id: str, payload: dict[str, Any]):
        """Generate a Cosmos clip for every scene in a variant sequentially.

        Same as calling /render/cosmos/scene for each scene index in order.
        Returns a list of results. Failed scenes include an error key but do not
        stop processing of remaining scenes.
        """
        render_cosmos_scene = deps.resolve("render_cosmos_scene")
        logger = deps.resolve("logger")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")

        plan = proj.meta.get("last_plan")
        if not plan or not (plan.get("variants") or []):
            raise HTTPException(400, "No plan generated — run Plan first.")

        variant_index = int((payload or {}).get("variant_index") or 0)
        variants = plan["variants"]
        if variant_index < 0 or variant_index >= len(variants):
            raise HTTPException(400, "variant_index out of range")

        scenes = (variants[variant_index].get("scenes") or [])
        results = []
        for idx in range(len(scenes)):
            per_scene_payload = {**(payload or {}), "scene_index": idx, "variant_index": variant_index}
            try:
                r = render_cosmos_scene(project_id, per_scene_payload)
                results.append(r)
            except UserFacingError as e:
                results.append({"ok": False, "scene_index": idx, "error": e.message, "hint": e.hint})
            except Exception:
                logger.exception("Cosmos scene render failed for scene %s", idx)
                results.append({"ok": False, "scene_index": idx, "error": "Cosmos scene render failed"})

        return {"ok": True, "provider": "nvidia-cosmos", "results": results, "total": len(scenes)}

    @router.post("/v1/projects/{project_id}/render/azure_foundry/scene")
    def render_azure_foundry_scene(project_id: str, payload: dict[str, Any]):
        """Generate a single video clip for one scene using the hosted Azure AI Foundry
        Cosmos3-Super managed-compute deployment.

        Unlike /render/cosmos/scene (a self-hosted NIM), this calls a hosted Foundry
        ``GlobalManagedCompute`` deployment with an API key — no local GPU required.

        payload fields (all optional):
          scene_index   : int   (default 0)
          variant_index : int   (default 0)
          seed          : int
          steps         : int
          guidance_scale: float
          num_frames    : int
          fps           : float
          resolution    : str   e.g. "720_16_9" (see Settings → Azure Foundry Cosmos3)
          use_keyframe  : bool  if true and variant has a rendered keyframe,
                                passes it as the init image
        """
        _COSMOS3_SHAPES = deps.resolve("_COSMOS3_SHAPES")
        _azure_foundry_client = deps.resolve("_azure_foundry_client")
        _render_provider_status = deps.resolve("_render_provider_status")
        render_settings = deps.resolve("render_settings")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")

        provider_status = _render_provider_status()
        azure_foundry_status = provider_status.get("azure_foundry") or {}
        if not azure_foundry_status.get("configured"):
            raise UserFacingError(
                "Azure AI Foundry Cosmos3 is not configured.",
                hint=(
                    "Set the Endpoint URL and Deployment name in Settings → GPU / Render Runtime → "
                    "Azure Foundry Cosmos3, then add an API key in Settings → Secrets."
                ),
                code="AZURE_FOUNDRY_NOT_CONFIGURED",
                status_code=400,
            )
        if not azure_foundry_status.get("has_api_key"):
            raise UserFacingError(
                "Azure Foundry API key is not set.",
                hint="Add the Azure Foundry API key in Settings → Secrets, then retry.",
                code="AZURE_FOUNDRY_NO_API_KEY",
                status_code=400,
            )

        plan = proj.meta.get("last_plan")
        if not plan or not (plan.get("variants") or []):
            raise HTTPException(400, "No plan generated — run Plan first.")

        variant_index = int((payload or {}).get("variant_index") or 0)
        variants = plan["variants"]
        if variant_index < 0 or variant_index >= len(variants):
            raise HTTPException(400, "variant_index out of range")

        variant = variants[variant_index]
        scenes = variant.get("scenes") or []
        scene_index = int((payload or {}).get("scene_index") or 0)
        if scene_index < 0 or scene_index >= len(scenes):
            raise HTTPException(400, f"scene_index {scene_index} out of range (0–{len(scenes)-1})")

        scene = scenes[scene_index]
        project_dir = store.project_dir(project_id)
        azure_foundry_cfg = dict(render_settings.get().get("azure_foundry") or {})
        client = _azure_foundry_client()

        prompt = str(scene.get("prompt") or "cinematic music video").strip()
        negative = str(scene.get("negative_prompt") or "blurry, low quality, text, watermark, logo").strip()
        steps = int((payload or {}).get("steps") or azure_foundry_cfg.get("steps") or 50)
        guidance_scale = float((payload or {}).get("guidance_scale") or azure_foundry_cfg.get("guidance_scale") or 7.0)
        num_frames = int((payload or {}).get("num_frames") or azure_foundry_cfg.get("num_frames") or 121)
        fps = float((payload or {}).get("fps") or azure_foundry_cfg.get("fps") or 24.0)
        seed = (payload or {}).get("seed")
        resolution = str((payload or {}).get("resolution") or azure_foundry_cfg.get("resolution") or "720_16_9")
        width, height = _COSMOS3_SHAPES.get(resolution, (1280, 720))

        out_dir = project_dir / "azure_foundry" / f"variant_{variant_index}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"scene_{scene_index:04d}.mp4"

        use_keyframe = bool((payload or {}).get("use_keyframe", False))
        init_image = None
        if use_keyframe:
            kf_path = project_dir / "stills" / f"variant_{variant_index}" / f"scene_{scene_index:04d}.png"
            if kf_path.exists():
                try:
                    from PIL import Image as PILImage
                    init_image = PILImage.open(str(kf_path)).convert("RGB")
                except Exception:
                    init_image = None

        if init_image is not None:
            result = client.image_to_video(
                image=init_image,
                out_path=out_path,
                prompt=prompt,
                negative_prompt=negative,
                width=width,
                height=height,
                fps=fps,
                num_frames=num_frames,
                steps=steps,
                guidance_scale=guidance_scale,
                seed=int(seed) if seed is not None else None,
            )
        else:
            result = client.text_to_video(
                prompt=prompt,
                out_path=out_path,
                negative_prompt=negative,
                width=width,
                height=height,
                fps=fps,
                num_frames=num_frames,
                steps=steps,
                guidance_scale=guidance_scale,
                seed=int(seed) if seed is not None else None,
            )

        rel = result.video_path.relative_to(project_dir).as_posix()
        return {
            "ok": True,
            "provider": "azure-foundry-cosmos",
            "video": rel,
            "video_abs": str(result.video_path),
            "scene_index": scene_index,
            "model": result.model,
            "duration_s": result.duration_s,
            "frames": result.frames,
            "fps": result.fps,
            "seed": result.seed,
        }

    @router.post("/v1/projects/{project_id}/render/azure_foundry/all_scenes")
    def render_azure_foundry_all_scenes(project_id: str, payload: dict[str, Any]):
        """Generate an Azure Foundry Cosmos3 clip for every scene in a variant sequentially.

        Same as calling /render/azure_foundry/scene for each scene index in order.
        Returns a list of results. Failed scenes include an error key but do not
        stop processing of remaining scenes.
        """
        render_azure_foundry_scene = deps.resolve("render_azure_foundry_scene")
        logger = deps.resolve("logger")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")

        plan = proj.meta.get("last_plan")
        if not plan or not (plan.get("variants") or []):
            raise HTTPException(400, "No plan generated — run Plan first.")

        variant_index = int((payload or {}).get("variant_index") or 0)
        variants = plan["variants"]
        if variant_index < 0 or variant_index >= len(variants):
            raise HTTPException(400, "variant_index out of range")

        scenes = (variants[variant_index].get("scenes") or [])
        results = []
        for idx in range(len(scenes)):
            per_scene_payload = {**(payload or {}), "scene_index": idx, "variant_index": variant_index}
            try:
                r = render_azure_foundry_scene(project_id, per_scene_payload)
                results.append(r)
            except UserFacingError as e:
                results.append({"ok": False, "scene_index": idx, "error": e.message, "hint": e.hint})
            except Exception:
                logger.exception("Azure Foundry scene render failed for scene %s", idx)
                results.append({"ok": False, "scene_index": idx, "error": "Azure Foundry scene render failed"})

        return {"ok": True, "provider": "azure-foundry-cosmos", "results": results, "total": len(scenes)}

    @router.post("/v1/projects/{project_id}/render/firefly/scenes")
    def render_firefly_scenes(project_id: str, req: RenderScenesRequest):
        """Generate one keyframe per scene using Adobe Firefly (standard or custom model)."""
        _firefly_client = deps.resolve("_firefly_client")
        _render_provider_status = deps.resolve("_render_provider_status")
        logger = deps.resolve("logger")
        render_settings = deps.resolve("render_settings")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        plan = proj.meta.get("last_plan")
        if not plan or not (plan.get("variants") or []):
            raise HTTPException(400, "No plan generated — run Plan first.")

        variants = plan["variants"]
        if req.variant_index < 0 or req.variant_index >= len(variants):
            raise HTTPException(400, "variant_index out of range")

        provider_status = _render_provider_status()
        firefly_status = provider_status.get("firefly") or {}
        if not firefly_status.get("configured"):
            raise UserFacingError(
                "Adobe Firefly credentials not configured.",
                hint="Open Settings → Adobe Firefly, save your Client ID and Client Secret, then retry.",
                code="FIREFLY_NOT_CONFIGURED",
                status_code=400,
            )

        firefly_cfg = dict(render_settings.get().get("firefly") or {})
        client = _firefly_client()
        variant = variants[req.variant_index]
        scenes = variant.get("scenes") or []
        if not scenes:
            raise HTTPException(400, "Selected variant has no scenes.")

        width = int(req.width or proj.meta.get("width") or 768)
        height = int(req.height or proj.meta.get("height") or 432)
        results = []
        project_dir = store.project_dir(project_id)
        stills_dir = project_dir / "stills" / f"variant_{req.variant_index}"
        stills_dir.mkdir(parents=True, exist_ok=True)

        for idx, scene in enumerate(scenes):
            prompt = str(scene.get("prompt") or "cinematic music video still").strip()
            negative = str(scene.get("negative_prompt") or req.negative_prompt or "").strip()
            seed = req.seed if req.seed is not None else None
            custom_model_id = str(req.model_id or firefly_cfg.get("custom_model_id") or "").strip() or None

            try:
                result = client.generate_image(
                    prompt=prompt,
                    width=width,
                    height=height,
                    negative_prompt=negative,
                    seed=seed,
                    style=str(firefly_cfg.get("style") or "none"),
                    content_class=str(firefly_cfg.get("content_class") or "photo"),
                    custom_model_id=custom_model_id,
                    timeout_s=180.0,
                )
                out_path = stills_dir / f"scene_{idx:04d}.png"
                result.image.save(str(out_path), format="PNG")
                rel = out_path.relative_to(project_dir).as_posix()
                results.append({
                    "scene_index": idx,
                    "path": rel,
                    "seed": result.seed,
                    "generation_id": result.generation_id,
                    "custom_model_id": result.custom_model_id,
                    "ok": True,
                })
            except UserFacingError:
                raise
            except Exception:
                logger.exception("Firefly scene render failed for scene %s", idx)
                results.append({"scene_index": idx, "ok": False, "error": "Firefly scene render failed"})

        return {"ok": True, "provider": "adobe-firefly", "results": results, "width": width, "height": height}

    @router.post("/v1/projects/{project_id}/render/firefly/video")
    def render_firefly_video(project_id: str, payload: dict[str, Any]):
        """Generate native Firefly video clips (text-to-video) for a plan variant.

        For each scene in the selected variant, submits a Firefly Video job and
        saves the returned MP4 under clips/variant_N/. Pass ``scene_index`` to
        render a single scene instead of the whole variant.
        """
        _firefly_client = deps.resolve("_firefly_client")
        _render_provider_status = deps.resolve("_render_provider_status")
        logger = deps.resolve("logger")
        render_settings = deps.resolve("render_settings")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        plan = proj.meta.get("last_plan")
        if not plan or not (plan.get("variants") or []):
            raise HTTPException(400, "No plan generated — run Plan first.")

        payload = payload or {}
        variants = plan["variants"]
        variant_index = int(payload.get("variant_index") or 0)
        if variant_index < 0 or variant_index >= len(variants):
            raise HTTPException(400, "variant_index out of range")

        provider_status = _render_provider_status()
        firefly_status = provider_status.get("firefly") or {}
        if not firefly_status.get("configured"):
            raise UserFacingError(
                "Adobe Firefly credentials not configured.",
                hint="Open Settings → Adobe Firefly, save your Client ID and Client Secret, then retry.",
                code="FIREFLY_NOT_CONFIGURED",
                status_code=400,
            )

        firefly_cfg = dict(render_settings.get().get("firefly") or {})
        client = _firefly_client()
        scenes = variants[variant_index].get("scenes") or []
        if not scenes:
            raise HTTPException(400, "Selected variant has no scenes.")

        width = int(payload.get("width") or proj.meta.get("width") or 1280)
        height = int(payload.get("height") or proj.meta.get("height") or 720)
        duration_s = float(payload.get("duration_s") or firefly_cfg.get("video_duration_s") or 5)
        custom_model_id = str(payload.get("model_id") or firefly_cfg.get("custom_model_id") or "").strip() or None
        seed = payload.get("seed")
        seed = int(seed) if seed is not None else None

        requested_scene = payload.get("scene_index")
        scene_indices = (
            [int(requested_scene)]
            if requested_scene is not None
            else list(range(len(scenes)))
        )

        project_dir = store.project_dir(project_id)
        clips_dir = project_dir / "clips" / f"variant_{variant_index}"
        clips_dir.mkdir(parents=True, exist_ok=True)

        results = []
        for idx in scene_indices:
            if idx < 0 or idx >= len(scenes):
                results.append({"scene_index": idx, "ok": False, "error": "scene_index out of range"})
                continue
            scene = scenes[idx]
            prompt = str(scene.get("prompt") or "cinematic music video clip").strip()
            negative = str(scene.get("negative_prompt") or payload.get("negative_prompt") or "").strip()
            try:
                result = client.generate_video(
                    prompt=prompt,
                    width=width,
                    height=height,
                    duration_s=duration_s,
                    negative_prompt=negative,
                    seed=seed,
                    custom_model_id=custom_model_id,
                )
                out_path = clips_dir / f"scene_{idx:04d}.mp4"
                out_path.write_bytes(result.video_bytes)
                rel = out_path.relative_to(project_dir).as_posix()
                results.append({
                    "scene_index": idx,
                    "path": rel,
                    "seed": result.seed,
                    "generation_id": result.generation_id,
                    "duration_s": result.duration_s,
                    "ok": True,
                })
            except UserFacingError:
                raise
            except Exception:
                logger.exception("Firefly video render failed for scene %s", idx)
                results.append({"scene_index": idx, "ok": False, "error": "Firefly video render failed"})

        return {
            "ok": True,
            "provider": "adobe-firefly",
            "kind": "video",
            "results": results,
            "width": width,
            "height": height,
        }

    @router.post("/v1/projects/{project_id}/render/firefly/assemble")
    def render_firefly_assemble(project_id: str, payload: dict[str, Any]):
        """Assemble Firefly-generated scene stills into a final MP4 video.

        Reads the PNGs from stills/variant_N/ that were produced by
        /render/firefly/scenes, assigns each scene's duration from the plan,
        and calls FFmpeg slideshow assembly + optional audio mux.
        """
        _project_audio_path = deps.resolve("_project_audio_path")
        assemble_slideshow = deps.resolve("assemble_slideshow")
        logger = deps.resolve("logger")
        mux_audio = deps.resolve("mux_audio")
        settings = deps.resolve("settings")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        plan = proj.meta.get("last_plan")
        if not plan or not (plan.get("variants") or []):
            raise HTTPException(400, "No plan generated — run Plan first.")

        variant_index = int((payload or {}).get("variant_index") or 0)
        variants = plan["variants"]
        if variant_index < 0 or variant_index >= len(variants):
            raise HTTPException(400, "variant_index out of range")

        variant = variants[variant_index]
        scenes = variant.get("scenes") or []
        if not scenes:
            raise HTTPException(400, "No scenes in selected variant.")

        project_dir = store.project_dir(project_id)
        stills_dir = project_dir / "stills" / f"variant_{variant_index}"
        imgs: list[Path] = []
        durations: list[float] = []
        for idx, scene in enumerate(scenes):
            img_path = stills_dir / f"scene_{idx:04d}.png"
            if img_path.exists():
                imgs.append(img_path)
                start = float(scene.get("start_s") or 0.0)
                end = float(scene.get("end_s") or (start + 4.0))
                durations.append(max(0.5, end - start))
            else:
                raise UserFacingError(
                    f"Scene {idx} still not found at {img_path.name}.",
                    hint="Run 'Render with Firefly' first to generate keyframes for all scenes.",
                    code="FIREFLY_STILL_MISSING",
                    status_code=400,
                )

        if not imgs:
            raise HTTPException(400, "No Firefly stills found for this variant.")

        out_path = project_dir / "output" / f"firefly_v{variant_index}.mp4"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        assemble_slideshow(
            ffmpeg_path=settings.ffmpeg_path,
            image_paths=imgs,
            durations_s=durations,
            out_mp4=out_path,
            fps=int((payload or {}).get("fps") or 24),
        )

        audio_path = _project_audio_path(proj)
        fallback_audio = project_dir / "audio.wav"
        if audio_path is not None or fallback_audio.exists():
            resolved_audio = audio_path or fallback_audio
            muxed = out_path.with_name(out_path.stem + "_muxed.mp4")
            try:
                mux_audio(settings.ffmpeg_path, video_mp4=out_path, audio_path=resolved_audio, out_mp4=muxed)
                out_path = muxed
            except Exception:
                logger.warning("Firefly audio mux failed", exc_info=True)

        rel = out_path.relative_to(project_dir).as_posix()
        return {"ok": True, "provider": "adobe-firefly", "video": rel, "video_abs": str(out_path)}

    @router.post("/v1/projects/{project_id}/render/imagineart/scenes")
    def render_imagineart_scenes(project_id: str, req: RenderScenesRequest):
        """Generate one keyframe per scene using ImagineArt hosted image generation."""
        _imagineart_client = deps.resolve("_imagineart_client")
        _render_provider_status = deps.resolve("_render_provider_status")
        logger = deps.resolve("logger")
        render_settings = deps.resolve("render_settings")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        plan = proj.meta.get("last_plan")
        if not plan or not (plan.get("variants") or []):
            raise HTTPException(400, "No plan generated — run Plan first.")

        variants = plan["variants"]
        if req.variant_index < 0 or req.variant_index >= len(variants):
            raise HTTPException(400, "variant_index out of range")

        provider_status = _render_provider_status()
        imagineart_status = provider_status.get("imagineart") or {}
        if not imagineart_status.get("configured"):
            raise UserFacingError(
                "ImagineArt API key not configured.",
                hint="Open Settings → Tokens, save your ImagineArt API key, then retry.",
                code="IMAGINEART_NOT_CONFIGURED",
                status_code=400,
            )
        if not imagineart_status.get("enabled"):
            raise UserFacingError(
                "ImagineArt provider is disabled.",
                hint="Open Settings → GPU / Render Runtime → ImagineArt and enable the provider.",
                code="IMAGINEART_DISABLED",
                status_code=400,
            )

        imagineart_cfg = dict(render_settings.get().get("imagineart") or {})
        client = _imagineart_client()
        variant = variants[req.variant_index]
        scenes = variant.get("scenes") or []
        if not scenes:
            raise HTTPException(400, "Selected variant has no scenes.")

        width = int(req.width or proj.meta.get("width") or 768)
        height = int(req.height or proj.meta.get("height") or 432)
        results = []
        project_dir = store.project_dir(project_id)
        stills_dir = project_dir / "stills" / f"variant_{req.variant_index}"
        stills_dir.mkdir(parents=True, exist_ok=True)

        for idx, scene in enumerate(scenes):
            prompt = str(scene.get("prompt") or "cinematic music video still").strip()
            seed = req.seed if req.seed is not None else None
            try:
                result = client.generate_image(
                    prompt=prompt,
                    width=width,
                    height=height,
                    style=str(imagineart_cfg.get("image_style") or "imagine-turbo"),
                    seed=seed,
                    timeout_s=float(imagineart_cfg.get("timeout_s") or 180),
                )
                out_path = stills_dir / f"scene_{idx:04d}.png"
                result.image.save(str(out_path), format="PNG")
                rel = out_path.relative_to(project_dir).as_posix()
                results.append({
                    "scene_index": idx,
                    "path": rel,
                    "seed": result.seed,
                    "model": result.model,
                    "ok": True,
                })
            except UserFacingError:
                raise
            except Exception:
                logger.exception("ImagineArt scene render failed for scene %s", idx)
                results.append({"scene_index": idx, "ok": False, "error": "ImagineArt scene render failed"})

        return {"ok": True, "provider": "imagineart", "results": results, "width": width, "height": height}

    @router.post("/v1/projects/{project_id}/render/imagineart/video")
    def render_imagineart_video(project_id: str, payload: dict[str, Any]):
        """Generate native ImagineArt video clips for plan scenes (text-to-video or image-to-video)."""
        _imagineart_client = deps.resolve("_imagineart_client")
        _render_provider_status = deps.resolve("_render_provider_status")
        logger = deps.resolve("logger")
        render_settings = deps.resolve("render_settings")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        plan = proj.meta.get("last_plan")
        if not plan or not (plan.get("variants") or []):
            raise HTTPException(400, "No plan generated — run Plan first.")

        payload = payload or {}
        variants = plan["variants"]
        variant_index = int(payload.get("variant_index") or 0)
        if variant_index < 0 or variant_index >= len(variants):
            raise HTTPException(400, "variant_index out of range")

        provider_status = _render_provider_status()
        imagineart_status = provider_status.get("imagineart") or {}
        if not imagineart_status.get("configured"):
            raise UserFacingError(
                "ImagineArt API key not configured.",
                hint="Open Settings → Tokens, save your ImagineArt API key, then retry.",
                code="IMAGINEART_NOT_CONFIGURED",
                status_code=400,
            )

        imagineart_cfg = dict(render_settings.get().get("imagineart") or {})
        client = _imagineart_client()
        variant = variants[variant_index]
        scenes = variant.get("scenes") or []
        if not scenes:
            raise HTTPException(400, "No scenes in selected variant.")

        scene_index = payload.get("scene_index")
        scene_indices = [int(scene_index)] if scene_index is not None else list(range(len(scenes)))
        use_keyframe = bool(payload.get("use_keyframe", False))
        video_style = str(payload.get("video_style") or imagineart_cfg.get("video_style") or "kling-1.0-pro")
        timeout_s = float(payload.get("timeout_s") or imagineart_cfg.get("timeout_s") or 600)

        project_dir = store.project_dir(project_id)
        clips_dir = project_dir / "clips" / f"variant_{variant_index}"
        clips_dir.mkdir(parents=True, exist_ok=True)
        stills_dir = project_dir / "stills" / f"variant_{variant_index}"
        results = []

        for idx in scene_indices:
            if idx < 0 or idx >= len(scenes):
                continue
            scene = scenes[idx]
            prompt = str(scene.get("prompt") or "cinematic music video clip").strip()
            init_image = None
            if use_keyframe:
                still_path = stills_dir / f"scene_{idx:04d}.png"
                if still_path.exists():
                    from PIL import Image

                    init_image = Image.open(still_path).convert("RGB")

            try:
                result = client.generate_video(
                    prompt=prompt,
                    style=video_style,
                    init_image=init_image,
                    timeout_s=timeout_s,
                    poll_interval_s=5.0,
                )
                out_path = clips_dir / f"scene_{idx:04d}.mp4"
                out_path.write_bytes(result.video_bytes)
                rel = out_path.relative_to(project_dir).as_posix()
                results.append({
                    "scene_index": idx,
                    "path": rel,
                    "generation_id": result.generation_id,
                    "model": result.model,
                    "ok": True,
                })
            except UserFacingError:
                raise
            except Exception:
                logger.exception("ImagineArt video render failed for scene %s", idx)
                results.append({"scene_index": idx, "ok": False, "error": "ImagineArt video render failed"})

        return {
            "ok": True,
            "provider": "imagineart",
            "results": results,
            "variant_index": variant_index,
        }

    @router.post("/v1/projects/{project_id}/render/imagineart/assemble")
    def render_imagineart_assemble(project_id: str, payload: dict[str, Any]):
        """Assemble ImagineArt-generated scene stills into a final MP4 video."""
        _project_audio_path = deps.resolve("_project_audio_path")
        assemble_slideshow = deps.resolve("assemble_slideshow")
        logger = deps.resolve("logger")
        mux_audio = deps.resolve("mux_audio")
        settings = deps.resolve("settings")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        plan = proj.meta.get("last_plan")
        if not plan or not (plan.get("variants") or []):
            raise HTTPException(400, "No plan generated — run Plan first.")

        variant_index = int((payload or {}).get("variant_index") or 0)
        variants = plan["variants"]
        if variant_index < 0 or variant_index >= len(variants):
            raise HTTPException(400, "variant_index out of range")

        variant = variants[variant_index]
        scenes = variant.get("scenes") or []
        if not scenes:
            raise HTTPException(400, "No scenes in selected variant.")

        project_dir = store.project_dir(project_id)
        stills_dir = project_dir / "stills" / f"variant_{variant_index}"
        imgs: list[Path] = []
        durations: list[float] = []
        for idx, scene in enumerate(scenes):
            img_path = stills_dir / f"scene_{idx:04d}.png"
            if img_path.exists():
                imgs.append(img_path)
                start = float(scene.get("start_s") or 0.0)
                end = float(scene.get("end_s") or (start + 4.0))
                durations.append(max(0.5, end - start))
            else:
                raise UserFacingError(
                    f"Scene {idx} still not found at {img_path.name}.",
                    hint="Run 'Render with ImagineArt' first to generate keyframes for all scenes.",
                    code="IMAGINEART_STILL_MISSING",
                    status_code=400,
                )

        if not imgs:
            raise HTTPException(400, "No ImagineArt stills found for this variant.")

        out_path = project_dir / "output" / f"imagineart_v{variant_index}.mp4"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        assemble_slideshow(
            ffmpeg_path=settings.ffmpeg_path,
            image_paths=imgs,
            durations_s=durations,
            out_mp4=out_path,
            fps=int((payload or {}).get("fps") or 24),
        )

        audio_path = _project_audio_path(proj)
        fallback_audio = project_dir / "audio.wav"
        if audio_path is not None or fallback_audio.exists():
            resolved_audio = audio_path or fallback_audio
            muxed = out_path.with_name(out_path.stem + "_muxed.mp4")
            try:
                mux_audio(settings.ffmpeg_path, video_mp4=out_path, audio_path=resolved_audio, out_mp4=muxed)
                out_path = muxed
            except Exception:
                logger.warning("ImagineArt audio mux failed", exc_info=True)

        rel = out_path.relative_to(project_dir).as_posix()
        return {"ok": True, "provider": "imagineart", "video": rel, "video_abs": str(out_path)}

    @router.post("/v1/projects/{project_id}/render/stills/scenes")
    @router.post("/v1/projects/{project_id}/render/comfyui/scenes")
    def render_scenes(project_id: str, req: RenderScenesRequest):
        _normalize_controlnet_units = deps.resolve("_normalize_controlnet_units")
        _normalize_render_loras = deps.resolve("_normalize_render_loras")
        _request_payload = deps.resolve("_request_payload")
        _resolve_optional_comfy_asset_name = deps.resolve("_resolve_optional_comfy_asset_name")
        _resolve_still_scene_selection = deps.resolve("_resolve_still_scene_selection")
        _safe_name_tag = deps.resolve("_safe_name_tag")
        _stable_seed = deps.resolve("_stable_seed")
        jobs = deps.resolve("jobs")
        render_prompt_from_scene = deps.resolve("render_prompt_from_scene")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        plan = proj.meta.get("last_plan")
        if not plan or not (plan.get("variants") or []):
            raise HTTPException(400, "No plan generated")

        variants = plan["variants"]
        if req.variant_index < 0 or req.variant_index >= len(variants):
            raise HTTPException(400, "variant_index out of range")

        variant = variants[req.variant_index]
        scenes = variant.get("scenes") or []
        if not scenes:
            raise HTTPException(400, "Selected variant has no scenes")

        created = []
        resolved_loras = _normalize_render_loras(getattr(req, "loras", []))
        raw_controlnet_units = _request_payload(req).get("controlnet_units") if isinstance(_request_payload(req).get("controlnet_units"), list) else list(getattr(req, "controlnet_units", []))
        if req.workflow_family == "controlnet" and not raw_controlnet_units and req.controlnet_model and req.reference_asset:
            raw_controlnet_units = [
                {
                    "model": req.controlnet_model,
                    "reference_asset": req.reference_asset,
                    "conditioning_mode": req.conditioning_mode,
                    "strength": req.controlnet_strength,
                }
            ]

        selection = _resolve_still_scene_selection(
            model_id=req.model_id,
            checkpoint=req.checkpoint,
            workflow_family=req.workflow_family,
            controlnet_model=req.controlnet_model,
            reference_asset=req.reference_asset,
            conditioning_mode=req.conditioning_mode,
            controlnet_units=raw_controlnet_units,
        )
        controlnet_units = _normalize_controlnet_units(
            raw_controlnet_units,
            engine=str(selection.get("engine") or "comfyui"),
            family=selection.get("family"),
        )
        if str(selection.get("workflow_family") or "") == "controlnet" and not controlnet_units:
            raise UserFacingError(
                "No compatible ControlNet units were selected",
                hint="Attach one or more compatible ControlNet units before running the still render.",
                code="CONTROLNET_MISSING",
                status_code=400,
            )
        vae_name = (
            _resolve_optional_comfy_asset_name(req.vae, folder="vae", allowed_kinds={"vae"})
            if str(selection.get("engine") or "comfyui") == "comfyui"
            else (str(req.vae or "").strip() or None)
        )
        model_tag = _safe_name_tag(req.model_id or selection.get("checkpoint") or "default")
        workflow_tag = _safe_name_tag(selection.get("workflow_family") or "txt2img")
        ref_tag = _safe_name_tag(req.source_asset or req.reference_asset or "noref")
        for idx, sc in enumerate(scenes):
            # Deterministic output path for caching
            out_dir = store.project_dir(project_id) / "outputs" / "images"
            out_dir.mkdir(parents=True, exist_ok=True)
            seed = int(req.seed) + idx if req.seed is not None else _stable_seed(project_id, req.variant_index, idx)
            out_path = out_dir / f"v{req.variant_index:02d}_scene{idx:03d}_{workflow_tag}_{model_tag}_{ref_tag}_seed{seed}.png"
            p = {
                "variant_index": req.variant_index,
                "scene_index": idx,
                "model_id": req.model_id,
                "prompt": render_prompt_from_scene(sc, fallback=""),
                "source_prompt": sc.get("prompt") or sc.get("prompt_pack") or "",
                "storyboard": (
                    dict(sc.get("storyboard"))
                    if isinstance(sc.get("storyboard"), dict)
                    else None
                ),
                "negative_prompt": req.negative_prompt,
                "seed": seed,
                "width": req.width,
                "height": req.height,
                "steps": req.steps,
                "cfg": req.cfg,
                "sampler": req.sampler,
                "checkpoint": selection.get("checkpoint"),
                "workflow_family": selection.get("workflow_family"),
                "source_asset": req.source_asset,
                "reference_asset": req.reference_asset,
                "inpaint_mask": req.inpaint_mask,
                "outpaint": _request_payload(req.outpaint) if req.outpaint else None,
                "conditioning_mode": selection.get("conditioning_mode"),
                "controlnet_model": req.controlnet_model,
                "controlnet_name": selection.get("controlnet_name"),
                "controlnet_strength": req.controlnet_strength,
                "controlnet_units": controlnet_units,
                "engine": selection.get("engine"),
                "family": selection.get("family"),
                "model_path": str(selection.get("model_path")) if selection.get("model_path") else None,
                "loras": resolved_loras,
                "vae": vae_name,
                "denoise_strength": req.denoise_strength,
                "hires_fix": _request_payload(req.hires_fix) if req.hires_fix else None,
                "refiner": _request_payload(req.refiner) if req.refiner else None,
                "upscaler": req.upscaler,
                "out_path": str(out_path),
            }
            job_type = "internal_still_scene" if str(selection.get("engine") or "comfyui") == "internal" else "comfyui_scene"
            job = jobs.create(project_id, job_type, p)
            created.append(job.__dict__)

        proj.meta.setdefault("jobs", []).extend(created)
        store.save(proj)

        return {"ok": True, "enqueued": len(created), "jobs": created}

    @router.post("/v1/projects/{project_id}/render/tensorrt-standalone")
    def render_tensorrt_standalone(project_id: str, req: TensorRTStandaloneRenderRequest):
        """Enqueue a standalone TensorRT image render job."""
        _server_resolved_tensorrt_payload = deps.resolve("_server_resolved_tensorrt_payload")
        jobs = deps.resolve("jobs")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        plan = proj.meta.get("last_plan")
        if not plan or not (plan.get("variants") or []):
            raise HTTPException(400, "No plan generated")

        payload = _server_resolved_tensorrt_payload(req)
        job = jobs.create(project_id, "tensorrt_standalone", payload)
        job.progress = {
            "stage": "queued",
            "current": 0,
            "total": 1,
            "percent": 0.0,
            "message": f"Queued TensorRT standalone render for model {payload['model_id']}",
        }
        jobs.save(job)
        proj.meta.setdefault("jobs", []).append(job.__dict__)
        store.save(proj)
        return {"ok": True, "job": job.__dict__}

    @router.post("/v1/projects/{project_id}/render/tensorrt-deforum", deprecated=True)
    def render_tensorrt_deforum(project_id: str, req: TensorRTStandaloneRenderRequest):
        """Compatibility route for the canonical TensorRT keyframe-video renderer.

        The former implementation generated simulated noise frames after merely
        deserializing an engine.  Release builds must never present that as model
        inference, so this route now performs the same server-side preflight and
        queues the canonical internal TensorRT video path.
        """
        _enqueue_internal_video_job = deps.resolve("_enqueue_internal_video_job")
        _public_render_preflight = deps.resolve("_public_render_preflight")
        _server_resolved_tensorrt_payload = deps.resolve("_server_resolved_tensorrt_payload")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")

        payload = _server_resolved_tensorrt_payload(req)
        payload["render_mode"] = "tensorrt"
        payload["compatibility_source"] = "tensorrt-deforum"
        job, preflight = _enqueue_internal_video_job(
            project_id,
            proj,
            payload,
            job_type="tensorrt_deforum",
            queued_message=f"Queued canonical TensorRT compatibility render for model {payload['model_id']}",
        )
        return {
            "ok": True,
            "job": job.__dict__,
            "preflight": _public_render_preflight(preflight),
            "compatibility": {
                "route": "tensorrt-deforum",
                "execution_mode": "canonical_tensorrt_keyframe_video",
                "legacy_deforum_schedule_applied": False,
            },
        }

    @router.post("/v1/projects/{project_id}/render/tensorrt-standalone/preview")
    def render_tensorrt_standalone_preview(project_id: str, req: TensorRTStandaloneRenderRequest):
        """Synchronously run a low-latency preview render."""
        _resolved_tensorrt_execution_payload = deps.resolve("_resolved_tensorrt_execution_payload")
        _server_resolved_tensorrt_payload = deps.resolve("_server_resolved_tensorrt_payload")
        logger = deps.resolve("logger")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")

        from ..services import tensorrt_standalone
        # Run the generation synchronously in the request thread
        try:
            payload = _resolved_tensorrt_execution_payload(_server_resolved_tensorrt_payload(req))
            # Override steps for fast preview
            payload["steps"] = min(payload.get("steps", 8), 8)
            
            # We need a custom run_preview in tensorrt_standalone
            result = tensorrt_standalone.run_preview(project_id, payload)
            return {"ok": True, "image": result["image"], "engine_used": result["engine_used"]}
        except UserFacingError:
            raise
        except Exception as exc:
            logger.exception("TensorRT preview render failed")
            raise HTTPException(500, "TensorRT preview render failed") from exc

    @router.post("/v1/projects/{project_id}/render/internal/video")
    def render_internal_video(project_id: str, req: InternalVideoRenderRequest):
        """Enqueue a full internal render job (CPU-safe baseline)."""
        _enqueue_internal_video_job = deps.resolve("_enqueue_internal_video_job")
        _public_render_preflight = deps.resolve("_public_render_preflight")
        _request_payload = deps.resolve("_request_payload")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")

        job, preflight = _enqueue_internal_video_job(
            project_id,
            proj,
            _request_payload(req),
        )
        return {
            "ok": True,
            "job": job.__dict__,
            "preflight": _public_render_preflight(preflight),
        }

    @router.post("/v1/projects/{project_id}/generation")
    def submit_generation(project_id: str, req: GenerationRequest):
        """Normalize a provider request onto the existing internal render queue."""
        normalized_generation_job = deps.resolve("normalized_generation_job")
        _enqueue_internal_video_job = deps.resolve("_enqueue_internal_video_job")
        _public_render_preflight = deps.resolve("_public_render_preflight")
        _request_payload = deps.resolve("_request_payload")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")

        payload = _request_payload(req.parameters)
        if req.renderer_id in {"hunyuan_video15", "ltx_25"}:
            payload["video_model_engine"] = req.renderer_id
            payload["temporal_mode"] = "video_model"
        elif req.renderer_id in {"diffusion", "tensorrt"}:
            payload["render_mode"] = req.renderer_id
        payload["_generation"] = {
            "schema_version": req.schema_version,
            "operation": req.operation,
            "provider_id": req.provider_id,
            "renderer_id": req.renderer_id,
        }
        job, preflight = _enqueue_internal_video_job(
            project_id,
            proj,
            payload,
            idempotency_key=req.idempotency_key,
            priority=req.priority,
        )
        return {
            "ok": True,
            "generation": normalized_generation_job(job),
            "preflight": _public_render_preflight(preflight),
        }

    @router.get("/v1/projects/{project_id}/render/motion_sequencer")
    def render_motion_sequencer(project_id: str, variant_index: int = 0, fps: int = 24):
        _active_parseq_manifest = deps.resolve("_active_parseq_manifest")
        _project_variant_for_render = deps.resolve("_project_variant_for_render")
        _resolved_project_duration_s = deps.resolve("_resolved_project_duration_s")
        parseq_adapter = deps.resolve("parseq_adapter")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        variant, scenes = _project_variant_for_render(proj, int(variant_index or 0))
        duration_s = _resolved_project_duration_s(proj, variant, scenes)
        analysis = proj.meta.get("analysis") if isinstance(proj.meta.get("analysis"), dict) else {}
        generated = parseq_adapter.build_parseq_manifest(
            variant=variant,
            analysis=analysis,
            fps=max(1, min(60, int(fps or variant.get("fps") or 24))),
            duration_s=duration_s,
        )
        active = _active_parseq_manifest(proj)
        manifest = active or generated
        parsed = parseq_adapter.parseq_manifest_to_internal_overrides(manifest)
        recipe_graph = parseq_adapter.build_render_recipe_graph(
            manifest=manifest,
            internal_request=(proj.meta.get("last_internal_render") if isinstance(proj.meta.get("last_internal_render"), dict) else {}),
        )
        return {
            "ok": True,
            "variant_index": int(variant_index or 0),
            "active": active,
            "generated": generated,
            "summary": parsed.get("summary"),
            "overrides": parsed.get("overrides"),
            "recipe_graph": recipe_graph,
        }

    @router.post("/v1/projects/{project_id}/render/motion_sequencer/apply")
    def render_motion_sequencer_apply(project_id: str, req: ParseqMotionApplyRequest):
        _project_variant_for_render = deps.resolve("_project_variant_for_render")
        _resolved_project_duration_s = deps.resolve("_resolved_project_duration_s")
        parseq_adapter = deps.resolve("parseq_adapter")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        variant, scenes = _project_variant_for_render(proj, int(req.variant_index or 0))
        duration_s = _resolved_project_duration_s(proj, variant, scenes)
        analysis = proj.meta.get("analysis") if isinstance(proj.meta.get("analysis"), dict) else {}
        manifest = req.manifest if isinstance(req.manifest, dict) else parseq_adapter.build_parseq_manifest(
            variant=variant,
            analysis=analysis,
            fps=int(req.fps or variant.get("fps") or 24),
            duration_s=duration_s,
        )
        parsed = parseq_adapter.parseq_manifest_to_internal_overrides(manifest)
        recipe_graph = parseq_adapter.build_render_recipe_graph(manifest=manifest, internal_request={})
        if req.activate:
            proj.meta["active_parseq_manifest"] = manifest
            proj.meta["render_recipe_graph"] = recipe_graph
            store.save(proj)
        return {
            "ok": True,
            "active": bool(req.activate),
            "manifest": manifest,
            "summary": parsed.get("summary"),
            "overrides": parsed.get("overrides"),
            "recipe_graph": recipe_graph,
        }

    @router.post("/v1/projects/{project_id}/render/internal/preflight")
    def render_internal_preflight(project_id: str, req: InternalVideoRenderRequest):
        _apply_active_parseq_motion = deps.resolve("_apply_active_parseq_motion")
        _internal_render_preflight_data = deps.resolve("_internal_render_preflight_data")
        _public_render_preflight = deps.resolve("_public_render_preflight")
        _request_payload = deps.resolve("_request_payload")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        payload, _parseq = _apply_active_parseq_motion(proj, _request_payload(req))
        return _public_render_preflight(_internal_render_preflight_data(project_id, payload))

    @router.post("/v1/projects/{project_id}/render/comfyui/motion_scenes")
    def render_motion_scenes(project_id: str, req: RenderMotionRequest):
        _normalize_render_loras = deps.resolve("_normalize_render_loras")
        _resolve_comfy_motion_selection = deps.resolve("_resolve_comfy_motion_selection")
        _resolve_optional_comfy_asset_name = deps.resolve("_resolve_optional_comfy_asset_name")
        _safe_name_tag = deps.resolve("_safe_name_tag")
        _stable_seed = deps.resolve("_stable_seed")
        jobs = deps.resolve("jobs")
        settings = deps.resolve("settings")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        plan = proj.meta.get("last_plan")
        if not plan or not (plan.get("variants") or []):
            raise HTTPException(400, "No plan generated")

        variants = plan["variants"]
        if req.variant_index < 0 or req.variant_index >= len(variants):
            raise HTTPException(400, "variant_index out of range")

        variant = variants[req.variant_index]
        scenes = variant.get("scenes") or []
        if not scenes:
            raise HTTPException(400, "Selected variant has no scenes")

        created = []
        resolved_loras = _normalize_render_loras(getattr(req, "loras", []))
        vae_name = _resolve_optional_comfy_asset_name(req.vae, folder="vae", allowed_kinds={"vae"})
        motion_selection = _resolve_comfy_motion_selection(
            model_id=req.model_id,
            checkpoint=req.checkpoint,
            svd_model_id=req.svd_model_id,
            svd_checkpoint=req.svd_checkpoint,
        )
        checkpoint = str(motion_selection.get("checkpoint") or settings.comfyui_checkpoint)
        svd_checkpoint = str(motion_selection.get("svd_checkpoint") or req.svd_checkpoint or "svd_xt.safetensors")
        model_tag = _safe_name_tag(req.model_id or checkpoint)
        svd_tag = _safe_name_tag(req.svd_model_id or svd_checkpoint or "svd")
        for idx, sc in enumerate(scenes):
            start = float(sc.get("start_s", idx * 5))
            end = float(sc.get("end_s", start + 5))
            duration_s = max(0.5, end - start)
            frames = max(1, int(round(duration_s * req.fps)))
            frames = min(frames, int(req.max_frames_per_scene))

            # Practical caps for SVD (most setups use 14 or 25 frames)
            if req.engine == "svd":
                frames = min(frames, 25)

            seed = int(req.seed) + idx if req.seed is not None else _stable_seed(project_id, req.variant_index, idx)
            pdir = store.project_dir(project_id)
            frames_dir = pdir / "outputs" / "frames" / f"v{req.variant_index:02d}" / f"scene{idx:03d}" / f"{req.engine}_{model_tag}_{svd_tag}_seed{seed}"
            out_clip = pdir / "outputs" / "clips" / f"v{req.variant_index:02d}_scene{idx:03d}_{req.engine}_{model_tag}_{svd_tag}_seed{seed}.mp4"
            p = {
                "variant_index": req.variant_index,
                "scene_index": idx,
                "model_id": req.model_id,
                "svd_model_id": req.svd_model_id,
                "prompt": sc.get("prompt") or "",
                "negative_prompt": req.negative_prompt,
                "seed": seed,
                "width": req.width,
                "height": req.height,
                "steps": req.steps,
                "cfg": req.cfg,
                "sampler": req.sampler,
                "checkpoint": checkpoint,
                "fps": req.fps,
                "frames": frames,
                "engine": req.engine,
                "frames_dir": str(frames_dir),
                "out_clip": str(out_clip),
                "loras": resolved_loras,
                "vae": vae_name,
                "motion_model_name": req.motion_model_name,
                "context_length": req.context_length,
                "context_overlap": req.context_overlap,
                "beta_schedule": req.beta_schedule,
                "svd_checkpoint": svd_checkpoint,
                "svd_num_steps": req.svd_num_steps,
                "svd_motion_bucket_id": req.svd_motion_bucket_id,
                "svd_fps_id": req.svd_fps_id,
                "svd_cond_aug": req.svd_cond_aug,
                "svd_decoding_t": req.svd_decoding_t,
                "device": req.device,
            }
            job = jobs.create(project_id, "comfyui_motion_scene", p)
            created.append(job.__dict__)

        proj.meta.setdefault("jobs", []).extend(created)
        store.save(proj)

        return {"ok": True, "enqueued": len(created), "jobs": created}

    @router.get("/v1/render/route")
    def get_video_route():
        """Return the current recommended video generation route (GPU vs Cloud)."""
        _recommend_video_route = deps.resolve("_recommend_video_route")
        return {"ok": True, **_recommend_video_route()}

    @router.post("/v1/render/route/preferences")
    def set_video_route_preferences(payload: dict[str, Any]):
        """Save video generation preference (auto / local_gpu / cosmos_cloud / comfyui)."""
        VIDEO_GENERATION_PREFERENCES = deps.resolve("VIDEO_GENERATION_PREFERENCES")
        _hardware_profile_invalidate = deps.resolve("_hardware_profile_invalidate")
        _recommend_video_route = deps.resolve("_recommend_video_route")
        render_settings = deps.resolve("render_settings")
        preference = str((payload or {}).get("preference") or "auto").strip().lower()
        if preference not in VIDEO_GENERATION_PREFERENCES:
            raise UserFacingError(
                f"Unknown preference '{preference}'.",
                hint=f"Choose one of: {', '.join(VIDEO_GENERATION_PREFERENCES)}",
                code="INVALID_VIDEO_PREFERENCE",
                status_code=400,
            )
        auto_prefer_gpu = bool((payload or {}).get("auto_prefer_gpu", True))
        cosmos_fallback = bool((payload or {}).get("cosmos_fallback", True))
        saved = render_settings.update({"video": {
            "preference": preference,
            "auto_prefer_gpu": auto_prefer_gpu,
            "cosmos_fallback": cosmos_fallback,
        }})
        _hardware_profile_invalidate()
        return {"ok": True, "video": saved.get("video"), "route": _recommend_video_route()}

    @router.post("/v1/projects/{project_id}/render/video/smart")
    def render_video_smart(project_id: str, payload: dict[str, Any]):
        """Route a video render to local GPU, NVIDIA Cosmos, or Azure AI Foundry Cosmos3
        based on preference.

        Accepts same fields as /render/cosmos/all_scenes and the internal video
        conductor. The router decides which backend to use; the caller can override
        with explicit route='local_gpu'|'cosmos_cloud'|'azure_foundry_cloud'.
        """
        render_azure_foundry_all_scenes = deps.resolve("render_azure_foundry_all_scenes")
        render_cosmos_all_scenes = deps.resolve("render_cosmos_all_scenes")
        run_pipeline = deps.resolve("run_pipeline")
        _recommend_video_route = deps.resolve("_recommend_video_route")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")

        explicit_route = str((payload or {}).get("route") or "").strip().lower()
        recommendation = _recommend_video_route(project_id)
        route = explicit_route if explicit_route in ("local_gpu", "cosmos_cloud", "azure_foundry_cloud") else recommendation["route"]

        if route == "cosmos_cloud":
            return render_cosmos_all_scenes(project_id, payload)

        if route == "azure_foundry_cloud":
            return render_azure_foundry_all_scenes(project_id, payload)

        if route == "local_gpu":
            # Kick off internal video render via the existing conductor flow
            variant_index = int((payload or {}).get("variant_index") or 0)
            preset = str((payload or {}).get("preset") or "balanced")
            return run_pipeline(project_id, variant_index=variant_index, preset=preset, mode="auto", engine="auto")

        raise UserFacingError(
            "No video generation route is available.",
            hint=(
                "Enable CUDA in Settings → GPU / Render Runtime, add your NVIDIA API key "
                "(same key as Nemotron) for Cosmos cloud, or configure Azure AI Foundry Cosmos3 "
                "(endpoint, deployment name, and API key) in Settings."
            ),
            code="NO_VIDEO_ROUTE",
            status_code=400,
        )

    @router.get("/v1/projects/{project_id}/pipeline/validate")
    def validate_pipeline(project_id: str, variant_index: int = 0, preset: str = "balanced", mode: str = "auto", engine: str = "auto"):
        _hardware_profile = deps.resolve("_hardware_profile")
        _recommend_pipeline = deps.resolve("_recommend_pipeline")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        plan = proj.meta.get("last_plan")
        if not plan or not (plan.get("variants") or []):
            raise HTTPException(400, "No plan generated")
        rec = _recommend_pipeline(project_id, preset=preset, mode=mode, engine=engine)
        return {"ok": True, "recommended": rec, "hardware": _hardware_profile()}

    @router.post("/v1/projects/{project_id}/render/conductor/plan")
    def render_conductor_plan(project_id: str, req: RenderConductorPlanRequest):
        NoRealRenderRouteError = deps.resolve("NoRealRenderRouteError")
        _build_project_snapshot = deps.resolve("_build_project_snapshot")
        _build_render_conductor_environment = deps.resolve("_build_render_conductor_environment")
        _build_render_conductor_intent = deps.resolve("_build_render_conductor_intent")
        _load_project_visual_dna = deps.resolve("_load_project_visual_dna")
        build_advisory_render_plan = deps.resolve("build_advisory_render_plan")
        build_visual_dna_prompt_hints = deps.resolve("build_visual_dna_prompt_hints")
        project_music_graph = deps.resolve("_project_music_graph")
        normalize_director_mode = deps.resolve("normalize_director_mode")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        plan = proj.meta.get("last_plan")
        if not plan or not (plan.get("variants") or []):
            raise HTTPException(400, "No plan generated")

        visual_dna = _load_project_visual_dna(proj)
        intent = _build_render_conductor_intent(project_id, proj, req)
        snapshot = _build_project_snapshot(proj, dna=visual_dna)
        environment = _build_render_conductor_environment()
        meta = proj.meta if isinstance(proj.meta, dict) else {}
        environment["director_mode"] = normalize_director_mode(meta.get("director_mode") or meta.get("creative_direction_mode"))
        environment["music_graph"] = project_music_graph(proj)
        try:
            advisory_plan = build_advisory_render_plan(intent, snapshot, environment=environment)
        except NoRealRenderRouteError as exc:
            diagnostics = "; ".join(exc.diagnostics)
            raise UserFacingError(
                "No requested real render route is currently available.",
                hint=diagnostics or "Install a supported local model or configure a hosted provider, then retry.",
                code="NO_RENDER_ROUTE",
                status_code=409,
            ) from exc
        plan_payload = advisory_plan.model_dump(mode="json")
        proj.meta["last_conductor_plan"] = plan_payload
        proj.meta["last_conductor_intent"] = intent.model_dump(mode="json")
        store.save(proj)
        return {
            "ok": True,
            "intent": intent.model_dump(mode="json"),
            "plan": plan_payload,
            "environment": environment,
            "visual_dna_hints": build_visual_dna_prompt_hints(visual_dna),
        }

    @router.post("/v1/projects/{project_id}/render/conductor/promote")
    def render_conductor_promote(project_id: str, req: RenderConductorPromoteRequest):
        promote_proxy_sections = deps.resolve("promote_proxy_sections")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        stored = proj.meta.get("last_conductor_plan") if isinstance(proj.meta.get("last_conductor_plan"), dict) else None
        if not stored:
            raise HTTPException(400, "No conductor plan available. Generate an advisory plan first.")
        if req.plan_id and str(stored.get("plan_id") or "") != str(req.plan_id):
            raise HTTPException(400, "Conductor plan_id does not match the saved plan")

        updated_plan, promoted = promote_proxy_sections(
            stored,
            scene_ids=list(req.scene_ids or []),
            target_engine=req.target_engine,
            quality_tier=str(req.quality_tier or "quality"),
            reason=req.reason,
        )
        plan_payload = updated_plan.model_dump(mode="json")
        promotions = list(proj.meta.get("conductor_promotions") or []) if isinstance(proj.meta.get("conductor_promotions"), list) else []
        promotions.append(
            {
                "at": time.time(),
                "plan_id": plan_payload.get("plan_id"),
                "scene_ids": promoted,
                "target_engine": req.target_engine,
                "quality_tier": req.quality_tier,
                "reason": req.reason,
            }
        )
        proj.meta["last_conductor_plan"] = plan_payload
        proj.meta["conductor_promotions"] = promotions[-20:]
        store.save(proj)
        return {
            "ok": True,
            "plan": plan_payload,
            "promoted_scene_ids": promoted,
            "promotions": promotions[-5:],
        }

    @router.get("/v1/projects/{project_id}/render/performer/plan")
    def get_render_performer_plan(project_id: str, variant_index: int = 0) -> dict[str, Any]:
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        stored = proj.meta.get("last_performer_plan") if isinstance(proj.meta.get("last_performer_plan"), dict) else None
        if not stored:
            return {"ok": True, "performer_plan": None, "stored": False}
        if int(stored.get("variant_index") or 0) != int(variant_index):
            return {"ok": True, "performer_plan": None, "stored": False, "variant_index": variant_index}
        return {"ok": True, "performer_plan": stored, "stored": True}

    @router.post("/v1/projects/{project_id}/render/performer/plan")
    def render_performer_plan(project_id: str, req: PerformerWorkflowPlanRequest) -> dict[str, Any]:
        _build_render_conductor_environment = deps.resolve("_build_render_conductor_environment")
        _performer_high_end_available = deps.resolve("_performer_high_end_available")
        build_performer_workflow_plan = deps.resolve("build_performer_workflow_plan")
        project_music_graph = deps.resolve("_project_music_graph")
        normalize_director_mode = deps.resolve("normalize_director_mode")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        plan = proj.meta.get("last_plan")
        if not plan or not (plan.get("variants") or []):
            raise HTTPException(400, "No plan generated")
        variants = plan.get("variants") if isinstance(plan.get("variants"), list) else []
        vi = int(req.variant_index or 0)
        if vi < 0 or vi >= len(variants):
            raise HTTPException(400, "Invalid variant_index")
        variant = variants[vi] if isinstance(variants[vi], dict) else {}
        scenes = [scene for scene in list(variant.get("scenes") or []) if isinstance(scene, dict)]
        meta = proj.meta if isinstance(proj.meta, dict) else {}
        music_graph = project_music_graph(proj)
        environment = _build_render_conductor_environment()
        performer_engines = environment.setdefault("engines", {})
        performer_hosted = dict(performer_engines.get("hosted_video") or {})
        performer_hosted["available"] = _performer_high_end_available()
        performer_hosted["capability"] = "audio_driven_performance_video"
        performer_engines["hosted_video"] = performer_hosted
        performer_plan = build_performer_workflow_plan(
            project_id=project_id,
            variant_index=vi,
            scenes=scenes,
            music_graph=music_graph,
            director_mode=normalize_director_mode(meta.get("director_mode") or meta.get("creative_direction_mode")),
            environment=environment,
            scene_ids=list(req.scene_ids or []),
            model_id=str(req.model_id or "wan_s2v_14b"),
        )
        proj.meta["last_performer_plan"] = performer_plan
        store.save(proj)
        return {
            "ok": True,
            "performer_plan": performer_plan,
            "music_graph": music_graph,
            "environment": environment,
        }

    @router.post("/v1/projects/{project_id}/render/performer/run")
    def render_performer_run(project_id: str, req: PerformerWorkflowRunRequest) -> dict[str, Any]:
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        stored = proj.meta.get("last_performer_plan") if isinstance(proj.meta.get("last_performer_plan"), dict) else None
        if not stored:
            raise HTTPException(400, "No performer plan available. Plan the performer lane first.")
        if int(stored.get("variant_index") or 0) != int(req.variant_index):
            raise HTTPException(400, "Performer plan does not match the selected variant")
        if req.plan_id and str(stored.get("plan_id") or "") != str(req.plan_id):
            raise HTTPException(400, "Performer plan_id does not match the saved plan")
        if not list(stored.get("tasks") or []):
            raise HTTPException(400, "Performer plan has no render tasks")

        raise UserFacingError(
            "No real Wan S2V performer adapter is available in this build.",
            hint="Install and configure a supported Wan S2V adapter before starting a performer render.",
            code="PERFORMER_ADAPTER_UNAVAILABLE",
            status_code=409,
        )

    @router.post("/v1/projects/{project_id}/pipeline/run")
    def run_pipeline(project_id: str, variant_index: int = 0, preset: str = "balanced", mode: str = "auto", engine: str = "auto"):
        """Enqueue an end-to-end pipeline: render (auto stills/motion) -> assemble final MP4.

        This endpoint is designed for one-click UX. It keeps full functionality internally.
        """
        render_internal_video = deps.resolve("render_internal_video")
        render_motion_scenes = deps.resolve("render_motion_scenes")
        render_scenes = deps.resolve("render_scenes")
        _build_internal_render_plan = deps.resolve("_build_internal_render_plan")
        _hardware_profile = deps.resolve("_hardware_profile")
        _preset_defaults = deps.resolve("_preset_defaults")
        _recommend_pipeline = deps.resolve("_recommend_pipeline")
        _render_provider_status = deps.resolve("_render_provider_status")
        jobs = deps.resolve("jobs")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        plan = proj.meta.get("last_plan")
        if not plan or not (plan.get("variants") or []):
            raise HTTPException(400, "No plan generated")

        mode_l = (mode or "auto").lower().strip()
        if mode_l == "internal":
            preset_l = str(preset or "balanced").lower().strip()
            requested_tier = "draft" if preset_l == "fast" else ("quality" if preset_l in ("quality", "ultra") else "auto")
            hw = _hardware_profile()
            provider_status = _render_provider_status(hw)
            tier_plan = _build_internal_render_plan(hw, requested_tier=requested_tier)
            tier_defaults = dict(tier_plan.get("defaults") or {})
            device_preference = str(tier_plan.get("device_preference") or "auto")
            if device_preference == "directml" and not bool((provider_status.get("directml") or {}).get("enabled", True)):
                device_preference = "cpu"
            internal_req = InternalVideoRenderRequest(
                variant_index=variant_index,
                fps_output=int(tier_defaults.get("fps_output", 24)),
                fps_render=int(tier_defaults.get("fps_render", 2)),
                width=int(tier_defaults.get("width", 768)),
                height=int(tier_defaults.get("height", 432)),
                steps=int(tier_defaults.get("steps", 15)),
                cfg=float(tier_defaults.get("cfg", 7.0)),
                keyframe_interval_s=float(tier_defaults.get("keyframe_interval_s", 5.0)),
                interpolation_engine=str(tier_defaults.get("interpolation_engine", os.getenv("EDMG_INTERPOLATION_ENGINE", "auto"))),
                model_id=os.getenv("EDMG_INTERNAL_MODEL_ID", "auto"),
                render_mode="auto",
                render_tier=str(tier_plan.get("applied_tier") or requested_tier),
                device_preference=device_preference,
                temporal_mode=str(tier_defaults.get("temporal_mode", "frame_img2img")),
                temporal_steps=int(tier_defaults.get("temporal_steps", 12)),
                refine_every_n_frames=int(tier_defaults.get("refine_every_n_frames", 1)),
                anchor_strength=float(tier_defaults.get("anchor_strength", 0.20)),
                prompt_blend=bool(tier_defaults.get("prompt_blend", True)),
            )
            res = render_internal_video(project_id, internal_req)
            return {"ok": True, "mode": str(res.get("preflight", {}).get("mode") or "internal"), "job": res.get("job"), "preflight": res.get("preflight")}

        defaults = _preset_defaults(preset)
        rec = _recommend_pipeline(project_id, preset=preset, mode=mode, engine=engine)
        if rec.get("mode") == "none":
            raise UserFacingError(
                "No render route is available.",
                hint=str(rec.get("reason") or "Install a supported local model or configure a hosted provider."),
                code="NO_RENDER_ROUTE",
                status_code=400,
            )

        if rec["mode"] in ("internal", "hosted"):
            hw = _hardware_profile()
            provider_status = _render_provider_status(hw)
            tier_plan = dict(rec.get("tier_plan") or _build_internal_render_plan(hw, requested_tier=("draft" if preset == "fast" else ("quality" if preset in ("quality", "ultra") else "auto"))))
            tier_defaults = dict(tier_plan.get("defaults") or {})
            device_preference = str(tier_plan.get("device_preference") or "auto")
            if device_preference == "directml" and not bool((provider_status.get("directml") or {}).get("enabled", True)):
                device_preference = "cpu"
            internal_req = InternalVideoRenderRequest(
                variant_index=variant_index,
                fps_output=int(tier_defaults.get("fps_output", 24)),
                fps_render=int(tier_defaults.get("fps_render", 2)),
                width=int(tier_defaults.get("width", defaults["stills"]["width"])),
                height=int(tier_defaults.get("height", defaults["stills"]["height"])),
                steps=int(tier_defaults.get("steps", defaults["stills"]["steps"])),
                cfg=float(tier_defaults.get("cfg", defaults["stills"]["cfg"])),
                keyframe_interval_s=float(tier_defaults.get("keyframe_interval_s", os.getenv("EDMG_INTERNAL_KEYFRAME_INTERVAL_S", "5.0"))),
                interpolation_engine=str(tier_defaults.get("interpolation_engine", os.getenv("EDMG_INTERPOLATION_ENGINE", "auto"))),
                model_id=str(rec.get("model_id") or os.getenv("EDMG_INTERNAL_MODEL_ID", "auto")),
                render_mode=("hosted" if rec["mode"] == "hosted" else "auto"),
                render_tier=str(tier_plan.get("applied_tier") or "auto"),
                device_preference=device_preference,
                temporal_mode=str(tier_defaults.get("temporal_mode", "frame_img2img")),
                temporal_steps=int(tier_defaults.get("temporal_steps", 12)),
                refine_every_n_frames=int(tier_defaults.get("refine_every_n_frames", 1)),
                anchor_strength=float(tier_defaults.get("anchor_strength", 0.20)),
                prompt_blend=bool(tier_defaults.get("prompt_blend", True)),
                allow_hosted_fallback=True,
            )
            res = render_internal_video(project_id, internal_req)
            effective_mode = str(res.get("preflight", {}).get("mode") or rec["mode"])
            selected = dict(rec)
            if effective_mode == "diffusion":
                selected["mode"] = "internal"
                selected["engine"] = "diffusion"
                selected["model_id"] = str(res.get("preflight", {}).get("model_id") or selected.get("model_id") or "auto")
            elif effective_mode == "hosted":
                selected["mode"] = effective_mode
            return {
                "ok": True,
                "preset": preset,
                "selected": selected,
                "render_mode": effective_mode,
                "job": res.get("job"),
                "preflight": res.get("preflight"),
            }

        if rec["mode"] == "stills":
            req = RenderScenesRequest(
                variant_index=variant_index,
                negative_prompt="(low quality, worst quality)",
                width=int(defaults["stills"]["width"]),
                height=int(defaults["stills"]["height"]),
                steps=int(defaults["stills"]["steps"]),
                cfg=float(defaults["stills"]["cfg"]),
                sampler=str(defaults["stills"]["sampler"]),
            )
            enq = render_scenes(project_id, req)
            assemble_fps = 24
        else:
            eng = rec["engine"] or "animatediff"
            req = RenderMotionRequest(
                variant_index=variant_index,
                negative_prompt="(low quality, worst quality)",
                width=int(defaults["stills"]["width"]),
                height=int(defaults["stills"]["height"]),
                steps=int(defaults["stills"]["steps"]),
                cfg=float(defaults["stills"]["cfg"]),
                sampler=str(defaults["stills"]["sampler"]),
                fps=int(defaults["motion"]["fps"]),
                max_frames_per_scene=int(defaults["motion"]["max_frames"]),
                engine=eng,
                motion_model_name="mm_sd_v15_v2.ckpt",
                context_length=16,
                context_overlap=4,
                beta_schedule="autoselect",
                svd_checkpoint="svd_xt.safetensors",
                svd_num_steps=25,
                svd_motion_bucket_id=127,
                svd_fps_id=6,
                svd_cond_aug=0.02,
                svd_decoding_t=14,
                device="cuda",
            )
            enq = render_motion_scenes(project_id, req)
            assemble_fps = int(defaults["motion"]["fps"])

        assemble_job = jobs.create(project_id, "assemble_variant", {"variant_index": variant_index, "fps": assemble_fps})
        return {
            "ok": True,
            "preset": preset,
            "selected": rec,
            "render_enqueued": enq.get("enqueued"),
            "assemble_job": assemble_job.__dict__,
        }

    @router.get("/v1/render/animation_presets")
    def animation_presets():
        """List the one-click animation presets (quality + motion intensity buttons)."""
        autoconfig = deps.resolve("autoconfig")
        return {"ok": True, "presets": autoconfig.list_presets()}

    @router.post("/v1/projects/{project_id}/render/auto")
    def render_auto(project_id: str, req: AutoAnimateRequest):
        """AI auto-configure render settings for a chosen animation preset, then
        optionally launch the full workflow on the internal renderer or ComfyUI.

        Manual configuration endpoints (``/render/internal/video``,
        ``/render/comfyui/motion_scenes``, etc.) remain available unchanged; this is
        an additive "push a button and the AI sets everything, then renders" layer.
        """
        render_animate_layers = deps.resolve("render_animate_layers")
        render_internal_video = deps.resolve("render_internal_video")
        render_motion_scenes = deps.resolve("render_motion_scenes")
        _build_internal_render_plan = deps.resolve("_build_internal_render_plan")
        _comfyui_available_quick = deps.resolve("_comfyui_available_quick")
        _hardware_profile = deps.resolve("_hardware_profile")
        _render_provider_status = deps.resolve("_render_provider_status")
        _resolved_project_duration_s = deps.resolve("_resolved_project_duration_s")
        _tensorrt_sd15_bundle_available = deps.resolve("_tensorrt_sd15_bundle_available")
        autoconfig = deps.resolve("autoconfig")
        jobs = deps.resolve("jobs")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        plan = proj.meta.get("last_plan")
        if not plan or not (plan.get("variants") or []):
            raise HTTPException(400, "No plan generated")
        variants = plan["variants"]
        vi = int(req.variant_index)
        if vi < 0 or vi >= len(variants):
            raise HTTPException(400, "Invalid variant_index")
        variant = variants[vi]
        scenes = variant.get("scenes") or []

        preset = autoconfig.resolve_preset(req.preset)
        if preset is None:
            raise UserFacingError(
                f"Unknown animation preset '{req.preset}'",
                hint="Call GET /v1/render/animation_presets for the available preset ids.",
                code="UNKNOWN_PRESET",
                status_code=400,
            )

        duration_s = _resolved_project_duration_s(proj, variant, scenes)
        fps = int(req.fps or variant.get("fps") or 24)

        hw = _hardware_profile()
        provider_status = _render_provider_status(hw)
        requested_tier = preset.quality if preset.quality in ("draft", "balanced", "quality") else "auto"
        tier_plan = _build_internal_render_plan(hw, requested_tier=requested_tier, duration_s=duration_s)
        tier_defaults = dict(tier_plan.get("defaults") or {})
        device_preference = str(tier_plan.get("device_preference") or "auto")
        if device_preference == "directml" and not bool((provider_status.get("directml") or {}).get("enabled", True)):
            device_preference = "cpu"

        requested_engine = str(req.engine or "auto").lower().strip()
        comfy_probe_performed = requested_engine == "comfyui" or (
            requested_engine == "auto" and str(preset.engine_hint or "auto").lower().strip() == "comfyui"
        )
        comfy_ok = _comfyui_available_quick() if comfy_probe_performed else False
        cfg = autoconfig.build_autoconfig(
            preset,
            engine=req.engine,
            tier_defaults=tier_defaults,
            applied_tier=str(tier_plan.get("applied_tier") or "auto"),
            preferred_model=str(tier_plan.get("preferred_internal_model") or "auto"),
            device_preference=device_preference,
            duration_s=duration_s,
            fps=fps,
            variant_index=vi,
            source_asset=req.source_asset,
            comfyui_available=comfy_ok,
            tensorrt_sd15_available=_tensorrt_sd15_bundle_available(),
        )

        result: dict[str, Any] = {
            "ok": True,
            "config": cfg.to_public(),
            "engine": cfg.engine,
            "hardware": hw,
            "tier_plan": tier_plan,
            "comfyui_available": comfy_ok,
            "comfyui_probe_performed": comfy_probe_performed,
            "launched": False,
        }
        if not req.run:
            return result

        # Object/layer animation presets (parallax / segment / background) run on the
        # model-free layered renderer. Masked / ComfyUI-regional presets need masks,
        # so they return the config and point at /render/animate_layers.
        if preset.is_layered:
            if preset.requires_masks or cfg.engine == "comfyui":
                result["notes"] = list(result["config"].get("notes") or []) + [
                    "This preset animates masked objects; call POST /render/animate_layers with masks."
                ]
                return result
            if not req.source_asset:
                result["notes"] = list(result["config"].get("notes") or []) + [
                    "Object animation needs a source image; pass source_asset."
                ]
                return result
            lr = cfg.layered_request or {}
            layered_req = LayeredAnimateRequest(
                source_asset=req.source_asset,
                mode=cfg.animation_mode,
                motion=cfg.motion_profile,
                fps=int(lr.get("fps", req.fps or 24)),
                duration_s=float(lr.get("duration_s", 5.0)),
                width=int(lr.get("width", 768)),
                height=int(lr.get("height", 432)),
            )
            res = render_animate_layers(project_id, layered_req)
            result.update(
                {
                    "launched": True,
                    "engine": "internal",
                    "animation_mode": cfg.animation_mode,
                    "job": res.get("job"),
                }
            )
            return result

        if cfg.engine == "comfyui" and cfg.comfyui_request is not None:
            motion_payload = {
                k: v for k, v in cfg.comfyui_request.items() if k in RenderMotionRequest.model_fields
            }
            enq = render_motion_scenes(project_id, RenderMotionRequest(**motion_payload))
            assemble_job = jobs.create(
                project_id, "assemble_variant", {"variant_index": vi, "fps": int(cfg.comfyui_request.get("fps", 24))}
            )
            result.update(
                {
                    "launched": True,
                    "render_enqueued": enq.get("enqueued"),
                    "jobs": enq.get("jobs"),
                    "assemble_job": assemble_job.__dict__,
                }
            )
            return result

        internal_payload = {
            k: v for k, v in cfg.internal_request.items() if k in InternalVideoRenderRequest.model_fields
        }
        res = render_internal_video(project_id, InternalVideoRenderRequest(**internal_payload))
        result.update(
            {
                "launched": True,
                "engine": "internal",
                "job": res.get("job"),
                "preflight": res.get("preflight"),
            }
        )
        return result

    @router.post("/v1/projects/{project_id}/render/animate_layers")
    def render_animate_layers(project_id: str, req: LayeredAnimateRequest):
        """Animate individual objects/regions within an image (parallax / masked / segment).

        Model-free compositing path; runs without a diffusion model or GPU.
        """
        _resolve_layered_refinement = deps.resolve("_resolve_layered_refinement")
        _resolve_project_reference_path = deps.resolve("_resolve_project_reference_path")
        autoconfig = deps.resolve("autoconfig")
        jobs = deps.resolve("jobs")
        store = deps.resolve("store")
        proj = store.get(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")

        source_path = _resolve_project_reference_path(project_id, req.source_asset)
        if source_path is None:
            raise UserFacingError(
                "Source image not found",
                hint="Upload an image under Render → References, then pass its path as source_asset.",
                code="ASSET_MISSING",
                status_code=400,
            )
        if req.mode == "masked" and not req.masks:
            raise UserFacingError(
                "Masked mode requires at least one mask",
                hint="Add a mask asset, or use parallax/segment modes.",
                code="MASK_REQUIRED",
                status_code=400,
            )

        if req.diffusion_refine:
            _resolve_layered_refinement(
                {
                    "model_id": req.model_id,
                    "device_preference": req.device_preference,
                }
            )

        profile = str(req.motion or "full_3d")
        schedule = autoconfig.build_motion_schedule(profile, duration_s=req.duration_s, fps=req.fps)
        payload = {
            "source_asset": req.source_asset,
            "mode": req.mode,
            "motion_profile": profile,
            "motion_schedule": schedule,
            "bands": int(req.bands),
            "masks": [m.model_dump() for m in req.masks],
            "subject_motion": float(req.subject_motion),
            "background_motion": float(req.background_motion),
            "fps": int(req.fps),
            "duration_s": float(req.duration_s),
            "width": int(req.width),
            "height": int(req.height),
            "include_audio": bool(req.include_audio),
            "diffusion_refine": bool(req.diffusion_refine),
            "model_id": str(req.model_id or "auto"),
            "device_preference": str(req.device_preference or "auto"),
            "refine_prompt": req.refine_prompt,
            "refine_negative": req.refine_negative,
            "refine_denoise": float(req.refine_denoise),
            "refine_steps": int(req.refine_steps),
            "refine_cfg": float(req.refine_cfg),
            "seed": req.seed,
        }
        job = jobs.create(project_id, "layered_animation", payload)
        job.progress = {
            "stage": "queued",
            "current": 0,
            "total": max(1, int(req.duration_s * req.fps) + 1),
            "percent": 0.0,
            "message": f"Queued {req.mode} object animation",
        }
        jobs.save(job)
        if isinstance(proj.meta, dict):
            proj.meta.setdefault("jobs", []).append(job.__dict__)
            store.save(proj)
        return {"ok": True, "job": job.__dict__, "animation_mode": req.mode, "motion_schedule": schedule}

    return router
