import pathlib
import sys

_BACKEND = pathlib.Path(__file__).resolve().parents[2]
_ROOT = pathlib.Path(__file__).resolve().parents[5]

for _p in (_BACKEND, _ROOT / 'src', _ROOT):
    _p_str = str(_p)
    if _p.exists() and _p_str not in sys.path:
        sys.path.insert(0, _p_str)

try:
    import librosa  # type: ignore
    import soundfile as sf  # type: ignore

    def _write_wav(path: str, y, sr: int, norm: bool = False) -> None:
        sf.write(path, y, sr)

    if not hasattr(librosa, 'output'):
        class _Output:
            pass
        librosa.output = _Output()  # type: ignore[attr-defined]
    if not hasattr(librosa.output, 'write_wav'):
        librosa.output.write_wav = _write_wav  # type: ignore[attr-defined]
except Exception:
    pass

import pytest

_TEST_AUDIO_FIXTURE = (
    _ROOT
    / "tests"
    / "fixtures"
    / "audio"
    / "LANDR-Walkin' In That Rundown Town-Warm-Medium-REV_V1.wav"
)

@pytest.fixture(scope='session')
def test_audio_file():
    """Provide the committed real-audio fixture for analyzer tests."""
    assert _TEST_AUDIO_FIXTURE.exists(), f"Missing test audio fixture: {_TEST_AUDIO_FIXTURE}"
    return str(_TEST_AUDIO_FIXTURE)
