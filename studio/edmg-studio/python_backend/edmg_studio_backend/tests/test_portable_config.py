from __future__ import annotations

import json
from pathlib import Path


def test_root_config_uses_portable_paths_and_ignores_local_override() -> None:
    root = Path(__file__).resolve().parents[5]
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    paths = config["paths"]

    assert all(not Path(value).is_absolute() for value in paths.values())
    assert "/config.local.json" in (root / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_deployment_config_recursively_overlays_local_file(tmp_path: Path, monkeypatch) -> None:
    from deploy import DeploymentManager

    (tmp_path / "config.json").write_text(
        json.dumps({"paths": {"cache_dir": "./cache"}, "ui": {"port": 7860}}),
        encoding="utf-8",
    )
    (tmp_path / "config.local.json").write_text(
        json.dumps({"paths": {"cache_dir": "D:\\edmg-cache"}, "ui": {"share": True}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    config = DeploymentManager().config

    assert config["paths"]["cache_dir"] == "D:\\edmg-cache"
    assert config["ui"] == {"port": 7860, "share": True}
