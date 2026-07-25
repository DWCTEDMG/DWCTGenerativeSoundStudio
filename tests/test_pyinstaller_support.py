import importlib.util
import zipfile
from pathlib import Path

import pytest


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


def test_nltk_release_resources_are_immutable_and_checksummed():
    pyinstaller_support = _load_pyinstaller_support()

    resources = pyinstaller_support.pinned_nltk_resource_manifest()

    assert [resource["name"] for resource in resources] == [
        "punkt",
        "punkt_tab",
        "stopwords",
        "vader_lexicon",
    ]
    for resource in resources:
        assert pyinstaller_support.NLTK_DATA_COMMIT in resource["url"]
        assert len(resource["sha256"]) == 64
        assert resource["size"] > 0


def test_pyinstaller_support_does_not_use_dynamic_nltk_downloader():
    repo_root = Path(__file__).resolve().parents[1]
    source = (
        repo_root / "studio" / "edmg-studio" / "python_backend" / "pyinstaller_support.py"
    ).read_text(encoding="utf-8")

    assert "nltk.download(" not in source


def test_ensure_pycparser_compat_modules_creates_legacy_tables(tmp_path):
    pyinstaller_support = _load_pyinstaller_support()
    package_dir = tmp_path / "pycparser"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")

    created = pyinstaller_support.ensure_pycparser_compat_modules(package_dir)

    assert {path.name for path in created} == {"lextab.py", "yacctab.py"}
    assert "Compatibility stub" in (package_dir / "lextab.py").read_text(encoding="utf-8")
    assert "_lr_action = {}" in (package_dir / "yacctab.py").read_text(encoding="utf-8")


def test_remove_staged_nltk_resource_removes_zip_fallback(tmp_path):
    pyinstaller_support = _load_pyinstaller_support()
    tokenizers_dir = tmp_path / "tokenizers"
    tokenizers_dir.mkdir()
    stale_zip = tokenizers_dir / "punkt.zip"
    stale_zip.write_text("not a zip", encoding="utf-8")

    pyinstaller_support._remove_staged_nltk_resource(tmp_path, "punkt")

    assert not stale_zip.exists()


def test_safe_zip_extraction_rejects_path_traversal(tmp_path):
    pyinstaller_support = _load_pyinstaller_support()
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.txt", "blocked")

    with pytest.raises(RuntimeError, match="Unsafe path"):
        pyinstaller_support._extract_zip_safely(archive, tmp_path / "output")


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
