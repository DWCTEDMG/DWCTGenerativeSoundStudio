from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_probe():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_clap_capability.py"
    spec = importlib.util.spec_from_file_location("check_clap_capability_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_clap_probe_reports_versions_without_model_resolution(monkeypatch):
    probe = _load_probe()
    requirements = (("torch", "torch"), ("transformers", "transformers"))
    monkeypatch.setattr(probe.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(probe.importlib.metadata, "version", lambda name: f"locked-{name}")
    # Avoid importing optional packages in the unit test; the documented frozen
    # parity command exercises the real imports from the clap environment.
    requirements_with_missing = (*requirements, ("missing", "missing_module"))
    original_find_spec = probe.importlib.util.find_spec
    monkeypatch.setattr(
        probe.importlib.util,
        "find_spec",
        lambda name: None if name == "missing_module" else original_find_spec(name),
    )

    status = probe.capability_status(requirements_with_missing)

    assert status["ok"] is False
    assert status["missing"] == ["missing"]
    assert status["packages"] == [
        {
            "distribution": "torch",
            "module": "torch",
            "version": "locked-torch",
        },
        {
            "distribution": "transformers",
            "module": "transformers",
            "version": "locked-transformers",
        },
    ]
