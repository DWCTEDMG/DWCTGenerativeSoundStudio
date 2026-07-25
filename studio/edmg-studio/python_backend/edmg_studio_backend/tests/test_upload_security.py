from __future__ import annotations

import pytest

from edmg_studio_backend import app as backend_app


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("CON.png", "_CON.png"),
        ("CON.preview.png", "_CON.preview.png"),
        ("lpt9.render.mask.png", "_lpt9.render.mask.png"),
        ("ordinary.preview.png", "ordinary.preview.png"),
    ],
)
def test_upload_filename_blocks_windows_device_names_with_any_extension(
    filename: str,
    expected: str,
) -> None:
    assert backend_app._safe_upload_filename(filename, "upload.bin") == expected
