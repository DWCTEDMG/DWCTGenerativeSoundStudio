from __future__ import annotations

import json
from pathlib import Path


def test_launcher_defaults_keep_models_local_and_preserve_provider_selection() -> None:
    root = Path(__file__).resolve().parents[1]
    defaults_path = root / "studio" / "edmg-studio" / "launcher_env.defaults.json"
    defaults = json.loads(defaults_path.read_text(encoding="utf-8"))

    assert defaults["EDMG_MODEL_STORAGE_MODE"] == "local_cache"
    assert defaults["HF_HUB_ENABLE_HF_TRANSFER"] == "1"
    assert defaults["EDMG_HF_TRANSFER_CONCURRENCY"] == "4"
    assert "EDMG_HF_BUCKET_MODEL_CACHE" not in defaults
    assert "EDMG_HF_BUCKET_ID" not in defaults
    assert "EDMG_HF_BUCKET_PREFIX" not in defaults
