import importlib.util
from pathlib import Path


def _load_pyinstaller_support():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "studio" / "edmg-studio" / "python_backend" / "pyinstaller_support.py"
    spec = importlib.util.spec_from_file_location("pyinstaller_support_test_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_required_nltk_resources_include_vader_and_punkt_tab():
    pyinstaller_support = _load_pyinstaller_support()

    assert pyinstaller_support.required_nltk_resources() == (
        "punkt",
        "punkt_tab",
        "stopwords",
        "vader_lexicon",
    )


def test_ensure_pycparser_compat_modules_creates_legacy_tables(tmp_path):
    pyinstaller_support = _load_pyinstaller_support()
    package_dir = tmp_path / "pycparser"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")

    created = pyinstaller_support.ensure_pycparser_compat_modules(package_dir)

    assert {path.name for path in created} == {"lextab.py", "yacctab.py"}
    assert "Compatibility stub" in (package_dir / "lextab.py").read_text(encoding="utf-8")
    assert "_lr_action = {}" in (package_dir / "yacctab.py").read_text(encoding="utf-8")


def test_local_scipy_hook_avoids_missing_cdflib_false_positive():
    repo_root = Path(__file__).resolve().parents[1]
    hook_path = (
        repo_root
        / "studio"
        / "edmg-studio"
        / "python_backend"
        / "pyinstaller_hooks"
        / "hook-scipy.special._ufuncs.py"
    )

    hook_text = hook_path.read_text(encoding="utf-8")

    assert 'hiddenimports = ["scipy.special._ufuncs_cxx"]' in hook_text
    assert '"scipy.special._special_ufuncs"' in hook_text
    assert '"scipy.special._cdflib"' not in hook_text
