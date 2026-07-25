import os
import pathlib
import tempfile


_BACKEND = pathlib.Path(__file__).resolve().parent


def _configure_pytest_temproot() -> None:
    if os.environ.get("PYTEST_DEBUG_TEMPROOT"):
        return

    candidates = []
    override = os.environ.get("EDMG_PYTEST_TEMPROOT")
    if override:
        candidates.append(pathlib.Path(override))
    candidates.extend([
        pathlib.Path(tempfile.gettempdir()) / "edmg-studio-pytest",
        _BACKEND / ".pytest-tmp",
    ])

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        os.environ["PYTEST_DEBUG_TEMPROOT"] = str(candidate)
        return


_configure_pytest_temproot()
