from __future__ import annotations

import runpy
import sys
from pathlib import Path

import numpy as np


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: rife_compat_entry.py <inference-script> [arguments...]")
    compatibility_aliases = {
        "bool": bool,
        "float": float,
        "int": int,
        "object": object,
        "str": str,
    }
    for name, value in compatibility_aliases.items():
        if name not in np.__dict__:
            setattr(np, name, value)
    inference = Path(sys.argv[1]).expanduser().resolve(strict=True)
    sys.path.insert(0, str(inference.parent))
    sys.argv = [str(inference), *sys.argv[2:]]
    runpy.run_path(str(inference), run_name="__main__")


if __name__ == "__main__":
    main()
