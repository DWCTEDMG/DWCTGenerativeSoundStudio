from __future__ import annotations

import argparse
import sys
from pathlib import Path


KIT_ROOT = Path(__file__).resolve().parents[1]
AI_DIRECTOR_EXTENSION = KIT_ROOT / "extensions" / "edmg.ai_director"
if str(AI_DIRECTOR_EXTENSION) not in sys.path:
    sys.path.insert(0, str(AI_DIRECTOR_EXTENSION))

from edmg.ai_director import EdmgBackendClient, load_scene_plan  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke the EDMG AI Director backend contract from the Kit workspace.")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--scene-plan",
        type=Path,
        default=KIT_ROOT / "sample_projects" / "audio_reactive_stage" / "scene_plan.json",
    )
    parser.add_argument("--output-usda", type=Path)
    args = parser.parse_args()

    client = EdmgBackendClient(base_url=args.backend_url)
    status = client.nvidia_status()
    nvidia = status.get("nvidia") if isinstance(status.get("nvidia"), dict) else {}
    print(f"[kit-ai-director] Backend: {args.backend_url.rstrip('/')}")
    print(f"[kit-ai-director] NVIDIA mode: {nvidia.get('enabled')}")
    print(f"[kit-ai-director] NVIDIA profile: {nvidia.get('profile')}")

    scene_plan = load_scene_plan(args.scene_plan)
    usda_text = client.scene_plan_usda(scene_plan)
    print(f"[kit-ai-director] USDA preview bytes: {len(usda_text.encode('utf-8'))}")

    if args.output_usda:
        args.output_usda.parent.mkdir(parents=True, exist_ok=True)
        args.output_usda.write_text(usda_text, encoding="utf-8", newline="\n")
        print(f"[kit-ai-director] Wrote: {args.output_usda}")

    print("[kit-ai-director] Smoke complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
