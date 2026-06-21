import sys
import pathlib
_ROOT = pathlib.Path(__file__).resolve().parents[1]
_STUDIO = _ROOT / 'studio' / 'edmg-studio'
_BACKEND = _ROOT / 'studio' / 'edmg-studio' / 'python_backend'
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
