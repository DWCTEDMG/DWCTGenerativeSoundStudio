from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "entrypoints.json"
REQUIRED_RETIREMENT_GATES = {
    "project-open-parity",
    "render-parity",
    "migration-parity",
    "package-upgrade-parity",
    "package-rollback-parity",
}


def _policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def test_entrypoint_policy_classifies_existing_launchers():
    policy = _policy()
    entries = policy["entrypoints"]
    paths = [entry["path"] for entry in entries]

    assert policy["schema_version"] == 1
    assert len(paths) == len(set(paths))
    assert {entry["classification"] for entry in entries} <= {
        "supported",
        "compatibility-frozen",
    }
    assert any(entry["classification"] == "supported" for entry in entries)
    for relative_path in paths:
        assert (ROOT / relative_path).is_file(), f"declared entrypoint is missing: {relative_path}"


def test_compatibility_entrypoints_require_complete_retirement_evidence():
    policy = _policy()
    assert set(policy["retirement_gates"]) == REQUIRED_RETIREMENT_GATES
    assert all(
        entry["classification"] == "compatibility-frozen"
        for entry in policy["entrypoints"]
        if entry["path"] in {
            "start.bat",
            "start.sh",
            "LAUNCH_EDMG_STUDIO_GUI.bat",
            "studio/edmg-studio/RUN_ME.bat",
            "studio/edmg-studio/run_me.sh",
        }
    )


def test_readme_canonical_launchers_match_policy():
    policy = _policy()
    supported = {
        entry["path"]
        for entry in policy["entrypoints"]
        if entry["classification"] == "supported"
    }
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert supported == {"RUN_ME.bat", "run_me.sh"}
    for relative_path in supported:
        assert relative_path in readme
