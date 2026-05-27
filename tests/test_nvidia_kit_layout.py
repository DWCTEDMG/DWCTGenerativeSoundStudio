from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
KIT_ROOT = REPO_ROOT / "studio" / "nvidia-kit"
VALIDATOR_PATH = KIT_ROOT / "tools" / "validate_kit_layout.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("validate_kit_layout", VALIDATOR_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nvidia_kit_layout_validates():
    validator = _load_validator()

    assert validator.validate_kit_layout(KIT_ROOT) == []


def test_nvidia_kit_layout_catches_missing_app(tmp_path):
    validator = _load_validator()

    errors = validator.validate_kit_layout(tmp_path)

    assert any("missing apps" in error for error in errors)

