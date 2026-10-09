"""Offline installed-model audit and opt-in GPU smoke; never claims production readiness."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import struct
import time
from datetime import datetime, timezone
from pathlib import Path


def _audit(path: Path) -> dict:
    config = json.loads((path / "config.json").read_text())
    index = json.loads((path / "model.safetensors.index.json").read_text())
    expected = index["weight_map"]
    errors = []
    size = 0
    for name in sorted(set(expected.values())):
        shard = (path / name).resolve()
        if not shard.is_relative_to(path.resolve()):
            errors.append(f"unauthorized shard: {name}")
            continue
        if not shard.is_file():
            errors.append(f"missing shard: {name}")
            continue
        size += shard.stat().st_size
        try:
            with shard.open("rb") as stream:
                prefix = stream.read(8)
                length = struct.unpack("<Q", prefix)[0]
                if length > 64 * 1024 * 1024:
                    raise ValueError("unbounded safetensors header")
                header = json.loads(stream.read(length))
            data_size = shard.stat().st_size - 8 - length
            for key, assigned in expected.items():
                if assigned != name:
                    continue
                start, end = header[key]["data_offsets"]
                if not 0 <= start <= end <= data_size:
                    raise ValueError(f"truncated tensor: {key}")
        except (OSError, ValueError, KeyError, struct.error) as exc:
            errors.append(f"invalid shard {name}: {exc}")
    revisions = set()
    for metadata in (path / ".cache/huggingface/download").glob("*.metadata"):
        lines = metadata.read_text().splitlines()
        if lines:
            revisions.add(lines[0])
    if len(revisions) != 1:
        errors.append("download metadata does not establish a single revision")
    return {"model_type": config["model_type"], "architectures": config.get("architectures", []),
            "download_revisions": sorted(revisions), "shards": len(set(expected.values())),
            "tensor_count": len(expected), "weight_bytes": size, "errors": errors,
            "state": "installed_structure_valid" if not errors else "incomplete",
            "integrity_scope": "index/header/length; payload hashes not verified"}


def audit(path: Path) -> dict:
    try:
        return _audit(path)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"state": "incomplete", "errors": [f"invalid model metadata: {exc}"],
                "integrity_scope": "index/header/length; payload hashes not verified"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_path", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--device-map", default="auto")
    parser.add_argument("--image", type=Path, help="Authorized image for a separate visual smoke")
    args = parser.parse_args()
    result = {"schema_version": 1, "checked_at": datetime.now(timezone.utc).isoformat(),
              "production_qualified": False, "model": audit(args.model_path)}
    exit_code = 0 if not result["model"]["errors"] else 1
    if args.smoke and not exit_code:
        started = time.monotonic()
        try:
            from edmg_studio_backend.services.director_providers import _local_transformers_json
            result["runtime"] = {name: importlib.metadata.version(name)
                                 for name in ("torch", "transformers", "accelerate", "safetensors")}
            import torch
            result["devices"] = [{"index": i, "name": torch.cuda.get_device_name(i),
                                  "uuid": str(getattr(torch.cuda.get_device_properties(i), "uuid", "unavailable"))}
                                 for i in range(torch.cuda.device_count())]
            content = [{"type": "text", "text": 'Return only JSON: {"status":"ok"}'}]
            if args.image:
                content = [{"type": "image", "image": str(args.image.resolve())},
                           {"type": "text", "text": 'Describe the dominant color. Return only JSON with one key "color".'}]
            text = _local_transformers_json(str(args.model_path), [
                {"role": "user", "content": content},
            ], device_map=args.device_map, max_new_tokens=64)
            parsed = json.loads(text)
            valid = (isinstance(parsed, dict) and str(parsed.get("color", "")).lower() == "red"
                     if args.image else parsed == {"status": "ok"})
            result["smoke"] = {"state": "image_understanding_executed" if args.image else "text_generation_executed", "output": text,
                               "structured_status_valid": valid,
                               "validation_scope": "red calibration image" if args.image else "status JSON"}
            if not result["smoke"]["structured_status_valid"]:
                exit_code = 1
        except Exception as exc:
            result["smoke"] = {"state": "failed", "error_type": type(exc).__name__, "error": str(exc)}
            exit_code = 1
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.receipt.with_suffix(args.receipt.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.receipt)
    print(json.dumps(result, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
