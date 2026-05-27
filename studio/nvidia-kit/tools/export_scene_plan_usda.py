from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "studio" / "edmg-studio" / "python_backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from edmg_studio_backend.services.nvidia_scene_plan import scene_plan_usda_text, validate_scene_plan  # noqa: E402


def export_scene_plan_usda(input_path: Path, output_path: Path) -> Path:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("scene plan root must be an object")

    errors = validate_scene_plan(payload)
    if errors:
        raise ValueError("; ".join(errors))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(scene_plan_usda_text(payload), encoding="utf-8", newline="\n")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export an EDMG scene_plan.json file as a starter USDA stage.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    try:
        output = export_scene_plan_usda(args.input, args.output)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"OK: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
