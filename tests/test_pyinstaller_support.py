import importlib.util
import sys
import types
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


def _load_tensorrt_hook(monkeypatch, *, is_linux, collected_binaries):
    repo_root = Path(__file__).resolve().parents[1]
    hook_path = (
        repo_root
        / "studio"
        / "edmg-studio"
        / "python_backend"
        / "pyinstaller_hooks"
        / "hook-tensorrt_libs.py"
    )
    calls = []

    pyinstaller_module = types.ModuleType("PyInstaller")
    pyinstaller_module.__path__ = []
    compat_module = types.ModuleType("PyInstaller.compat")
    compat_module.is_linux = is_linux
    utils_module = types.ModuleType("PyInstaller.utils")
    utils_module.__path__ = []
    hooks_module = types.ModuleType("PyInstaller.utils.hooks")
    hooks_module.PY_DYLIB_PATTERNS = ("*.dll", "*.dylib")

    def collect_dynamic_libs(package, *, search_patterns):
        calls.append((package, tuple(search_patterns)))
        return list(collected_binaries)

    hooks_module.collect_dynamic_libs = collect_dynamic_libs
    pyinstaller_module.compat = compat_module
    pyinstaller_module.utils = utils_module
    utils_module.hooks = hooks_module

    monkeypatch.setitem(sys.modules, "PyInstaller", pyinstaller_module)
    monkeypatch.setitem(sys.modules, "PyInstaller.compat", compat_module)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils", utils_module)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks_module)

    spec = importlib.util.spec_from_file_location("tensorrt_hook_test_module", hook_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module, calls


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


def test_linux_tensorrt_hook_excludes_only_windows_cross_builder_resources(monkeypatch):
    collected_binaries = [
        (
            "/opt/tensorrt_libs/libnvinfer_builder_resource_win_sm86.so.10.15.1",
            "tensorrt_libs",
        ),
        (
            "/opt/tensorrt_libs/libnvinfer_builder_resource_sm86.so.10.15.1",
            "tensorrt_libs",
        ),
        ("/opt/tensorrt_libs/libnvinfer.so.10", "tensorrt_libs"),
    ]

    hook, calls = _load_tensorrt_hook(
        monkeypatch,
        is_linux=True,
        collected_binaries=collected_binaries,
    )

    assert calls == [("tensorrt_libs", ("*.dll", "*.dylib", "*.so.*"))]
    assert hook.binaries == collected_binaries[1:]


def test_windows_tensorrt_hook_preserves_upstream_collection(monkeypatch):
    collected_binaries = [
        (r"C:\\TensorRT\\nvinfer_10.dll", "tensorrt_libs"),
        (
            r"C:\\TensorRT\\libnvinfer_builder_resource_win_sm86.so.10.15.1",
            "tensorrt_libs",
        ),
    ]

    hook, calls = _load_tensorrt_hook(
        monkeypatch,
        is_linux=False,
        collected_binaries=collected_binaries,
    )

    assert calls == [("tensorrt_libs", ("*.dll", "*.dylib"))]
    assert hook.binaries == collected_binaries
