import sys
import pathlib
import os
import tempfile
_ROOT = pathlib.Path(__file__).resolve().parents[1]
_STUDIO = _ROOT / 'studio' / 'edmg-studio'
_BACKEND = _ROOT / 'studio' / 'edmg-studio' / 'python_backend'


def _configure_pytest_temproot() -> None:
    if os.environ.get("PYTEST_DEBUG_TEMPROOT"):
        return

    candidates = []
    override = os.environ.get("EDMG_PYTEST_TEMPROOT")
    if override:
        candidates.append(pathlib.Path(override))
    candidates.extend([
        pathlib.Path(tempfile.gettempdir()) / "edmg-studio-pytest",
        _ROOT / ".pytest-tmp",
    ])

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        os.environ["PYTEST_DEBUG_TEMPROOT"] = str(candidate)
        return


_configure_pytest_temproot()

if _STUDIO.exists():
    sys.path.insert(0, str(_STUDIO))
if _BACKEND.exists():
    sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_ROOT))

import pytest

_TEST_AUDIO_FIXTURE = (
    _ROOT
    / "tests"
    / "fixtures"
    / "audio"
    / "LANDR-Walkin' In That Rundown Town-Warm-Medium-REV_V1.wav"
)

@pytest.fixture(scope="session")
def test_audio_file():
    """Provide the committed real-audio fixture for analyzer tests."""
    assert _TEST_AUDIO_FIXTURE.exists(), f"Missing test audio fixture: {_TEST_AUDIO_FIXTURE}"
    return str(_TEST_AUDIO_FIXTURE)
