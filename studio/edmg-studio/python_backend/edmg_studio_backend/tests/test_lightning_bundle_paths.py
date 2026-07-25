from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from edmg_studio_backend import app as backend_app


def test_relative_lightning_bundle_output_resolves_under_studio_data(tmp_path, monkeypatch):
    monkeypatch.setattr(backend_app, "settings", SimpleNamespace(data_dir=tmp_path / "data"))

    output_dir = backend_app._resolve_lightning_bundle_output_dir("lightning/lightning_bundle")

    assert output_dir == (tmp_path / "data" / "cloud" / "lightning" / "lightning_bundle").resolve()


def test_relative_lightning_bundle_output_cannot_escape_studio_data(tmp_path, monkeypatch):
    monkeypatch.setattr(backend_app, "settings", SimpleNamespace(data_dir=tmp_path / "data"))

    with pytest.raises(HTTPException) as exc:
        backend_app._resolve_lightning_bundle_output_dir("../outside")

    assert exc.value.status_code == 400


def test_absolute_lightning_bundle_output_cannot_escape_studio_data(tmp_path, monkeypatch):
    monkeypatch.setattr(backend_app, "settings", SimpleNamespace(data_dir=tmp_path / "data"))

    with pytest.raises(HTTPException) as exc:
        backend_app._resolve_lightning_bundle_output_dir(str(tmp_path / "outside"))

    assert exc.value.status_code == 400
