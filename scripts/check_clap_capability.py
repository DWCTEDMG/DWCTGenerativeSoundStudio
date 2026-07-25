"""Offline-safe parity probe for the optional locked CLAP capability."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
from collections.abc import Iterable


REQUIRED_DISTRIBUTIONS = (
    ("torch", "torch"),
    ("transformers", "transformers"),
    ("librosa", "librosa"),
    ("soundfile", "soundfile"),
)


def capability_status(
    requirements: Iterable[tuple[str, str]] = REQUIRED_DISTRIBUTIONS,
) -> dict[str, object]:
    packages: list[dict[str, str]] = []
    missing: list[str] = []
    for distribution, module in requirements:
        if importlib.util.find_spec(module) is None:
            missing.append(distribution)
            continue
        packages.append(
            {
                "distribution": distribution,
                "module": module,
                "version": importlib.metadata.version(distribution),
            }
        )

    if not missing:
        # Import the public entry points used by CLAP adapters without creating
        # a model or consulting the network/model hub.
        from transformers import ClapModel, ClapProcessor  # noqa: F401

    return {
        "ok": not missing,
        "missing": missing,
        "offline": os.getenv("HF_HUB_OFFLINE") == "1",
        "packages": packages,
    }


def main() -> int:
    status = capability_status()
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
