from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_BACKEND = REPO_ROOT / "python_backend"
if str(PYTHON_BACKEND) not in sys.path:
    sys.path.insert(0, str(PYTHON_BACKEND))

from edmg_studio_backend.services.unreal_bridge_consumer import (  # noqa: E402
    UnrealSequenceImportPlan,
    build_unreal_sequence_import_plan,
    write_unreal_sequence_import_plan,
)


def _load_unreal_module():
    try:
        import unreal  # type: ignore
    except Exception:
        return None
    return unreal


def _ensure_return_dir(plan: UnrealSequenceImportPlan) -> Path:
    path = Path(plan.expected_return_dir).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_report(bundle_dir: Path, payload: dict[str, Any]) -> Path:
    target = bundle_dir / "unreal_import_report.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _resolve_asset_path(unreal_module, plan: UnrealSequenceImportPlan, replace_existing: bool) -> tuple[Any, str]:
    editor_assets = unreal_module.EditorAssetLibrary
    factory = unreal_module.LevelSequenceFactoryNew()
    asset_tools = unreal_module.AssetToolsHelpers.get_asset_tools()

    asset_name = plan.asset_name
    asset_path = f"{plan.content_path}/{asset_name}"
    if replace_existing and editor_assets.does_asset_exist(asset_path):
        if not editor_assets.delete_asset(asset_path):
            raise RuntimeError(f"Unable to delete existing asset: {asset_path}")

    if not replace_existing:
        counter = 2
        while editor_assets.does_asset_exist(asset_path):
            asset_name = f"{plan.asset_name}_{counter}"
            asset_path = f"{plan.content_path}/{asset_name}"
            counter += 1

    sequence = asset_tools.create_asset(asset_name, plan.content_path, unreal_module.LevelSequence, factory)
    if sequence is None:
        raise RuntimeError(f"Unable to create Level Sequence asset at {asset_path}")
    return sequence, asset_path


def _add_markers(unreal_module, sequence, plan: UnrealSequenceImportPlan) -> int:
    count = 0
    add_marked_frame = getattr(sequence, "add_marked_frame_to_sequence", None)
    time_unit = getattr(unreal_module, "MovieSceneTimeUnit", None)
    for marker in plan.markers:
        marked = unreal_module.MovieSceneMarkedFrame(
            frame_number=unreal_module.FrameNumber(int(marker.frame)),
            label=str(marker.label),
            is_determinism_fence=False,
        )
        if callable(add_marked_frame) and time_unit is not None:
            add_marked_frame(marked, time_unit.DISPLAY_RATE)
        else:
            sequence.add_marked_frame(marked)
        count += 1
    return count


def _build_sequence(unreal_module, sequence, plan: UnrealSequenceImportPlan) -> dict[str, Any]:
    sequence.set_display_rate(unreal_module.FrameRate(numerator=plan.fps, denominator=1))
    sequence.set_playback_start(int(plan.playback_start))
    sequence.set_playback_end(int(plan.playback_end))

    marker_count = _add_markers(unreal_module, sequence, plan)
    camera_cut_track = sequence.add_master_track(unreal_module.MovieSceneCameraCutTrack)

    created_cameras: list[dict[str, Any]] = []
    for shot in plan.shots:
        binding = sequence.add_spawnable_from_class(unreal_module.CineCameraActor)
        if hasattr(binding, "set_name"):
            binding.set_name(shot.camera_name)
        cut_section = camera_cut_track.add_section()
        cut_section.set_range(int(shot.start_frame), int(max(shot.end_frame, shot.start_frame + 1)))
        cut_section.set_camera_binding_id(binding.get_binding_id())
        created_cameras.append(
            {
                "shot_id": shot.shot_id,
                "camera_name": shot.camera_name,
                "start_frame": shot.start_frame,
                "end_frame": shot.end_frame,
                "approved": shot.approved,
            }
        )

    unreal_module.EditorAssetLibrary.save_loaded_asset(sequence, only_if_is_dirty=False)
    return {
        "marker_count": marker_count,
        "camera_count": len(created_cameras),
        "cameras": created_cameras,
    }


def run_import(
    bundle_dir: str | Path,
    *,
    content_path: str | None = None,
    asset_name: str | None = None,
    replace_existing: bool = False,
    dry_run: bool = False,
    plan_json: str | None = None,
) -> dict[str, Any]:
    plan = build_unreal_sequence_import_plan(
        bundle_dir,
        content_path=content_path,
        asset_name=asset_name,
    )
    bundle_root = Path(plan.bundle_dir).expanduser().resolve()
    return_dir = _ensure_return_dir(plan)

    if plan_json:
        write_unreal_sequence_import_plan(plan, plan_json)

    report: dict[str, Any] = {
        "ok": True,
        "mode": "dry_run" if dry_run else "import",
        "bundle_dir": str(bundle_root),
        "asset_path": plan.asset_path,
        "return_dir": str(return_dir),
        "expected_outputs": list(plan.expected_outputs),
        "diagnostics": list(plan.diagnostics),
        "plan": plan.to_dict(),
    }
    if dry_run:
        report["report_path"] = str(_write_report(bundle_root, report))
        return report

    unreal_module = _load_unreal_module()
    if unreal_module is None:
        raise RuntimeError("This script must run inside Unreal Editor, or use --dry-run outside Unreal.")

    sequence, asset_path = _resolve_asset_path(unreal_module, plan, replace_existing=replace_existing)
    build_result = _build_sequence(unreal_module, sequence, plan)
    unreal_module.EditorAssetLibrary.set_metadata_tag(sequence, "EDMG.BundleDir", plan.bundle_dir)
    unreal_module.EditorAssetLibrary.set_metadata_tag(sequence, "EDMG.ReturnDir", str(return_dir))
    unreal_module.EditorAssetLibrary.save_loaded_asset(sequence, only_if_is_dirty=False)

    report["asset_path"] = asset_path
    report["mode"] = "imported"
    report["sequence_name"] = plan.sequence_name
    report["build_result"] = build_result
    report["report_path"] = str(_write_report(bundle_root, report))
    return report


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import an EDMG Unreal bridge bundle into Unreal Sequencer.")
    parser.add_argument("--bundle-dir", required=True, help="Path to the exported Unreal bridge bundle directory.")
    parser.add_argument("--content-path", default=None, help="Destination Unreal Content Browser path, for example /Game/EDMG/Sequences.")
    parser.add_argument("--asset-name", default=None, help="Override the generated Level Sequence asset name.")
    parser.add_argument("--replace-existing", action="store_true", help="Delete an existing asset at the target path before creating the new sequence.")
    parser.add_argument("--dry-run", action="store_true", help="Build the import plan and report without requiring Unreal Editor.")
    parser.add_argument("--plan-json", default=None, help="Optional filesystem path for the generated import plan JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or sys.argv[1:]))
    result = run_import(
        args.bundle_dir,
        content_path=args.content_path,
        asset_name=args.asset_name,
        replace_existing=bool(args.replace_existing),
        dry_run=bool(args.dry_run),
        plan_json=args.plan_json,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
