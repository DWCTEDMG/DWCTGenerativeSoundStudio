from __future__ import annotations

import re
from pathlib import Path

from edmg_studio_backend import app as backend_app
from edmg_studio_backend.schemas import HealthResponse
from edmg_studio_backend.version import STUDIO_VERSION


def test_backend_runtime_api_health_and_package_versions_match() -> None:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)

    assert match is not None
    assert STUDIO_VERSION == match.group(1)
    assert backend_app.app.version == STUDIO_VERSION
    assert HealthResponse().version == STUDIO_VERSION
