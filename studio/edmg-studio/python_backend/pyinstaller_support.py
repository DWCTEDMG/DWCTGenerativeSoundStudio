from __future__ import annotations

import hashlib
import shutil
import urllib.request
import zipfile
from collections.abc import Iterable
from pathlib import Path

NLTK_RESOURCE_LOCATIONS: dict[str, tuple[str, ...]] = {
    "punkt": ("tokenizers/punkt",),
    "punkt_tab": ("tokenizers/punkt_tab",),
    "stopwords": ("corpora/stopwords",),
    "vader_lexicon": ("sentiment/vader_lexicon.zip", "sentiment/vader_lexicon"),
}

NLTK_DATA_COMMIT = "550b6625bcef1f2abff2ff770a5a0d272c9c6b2a"
NLTK_RESOURCE_ASSETS: dict[str, dict[str, str | int]] = {
    "punkt": {
        "category": "tokenizers",
        "file_name": "punkt.zip",
        "url": f"https://raw.githubusercontent.com/nltk/nltk_data/{NLTK_DATA_COMMIT}/packages/tokenizers/punkt.zip",
        "sha256": "51c3078994aeaf650bfc8e028be4fb42b4a0d177d41c012b6a983979653660ec",
        "size": 13_905_355,
    },
    "punkt_tab": {
        "category": "tokenizers",
        "file_name": "punkt_tab.zip",
        "url": f"https://raw.githubusercontent.com/nltk/nltk_data/{NLTK_DATA_COMMIT}/packages/tokenizers/punkt_tab.zip",
        "sha256": "e57f64187974277726a3417ca6f181ec5403676c717672eef6a748a7b20e0106",
        "size": 4_319_076,
    },
    "stopwords": {
        "category": "corpora",
        "file_name": "stopwords.zip",
        "url": f"https://raw.githubusercontent.com/nltk/nltk_data/{NLTK_DATA_COMMIT}/packages/corpora/stopwords.zip",
        "sha256": "48c0e52d8b52546e827f53761fb30300c0ab94f70660d28bd65ba0a86270946b",
        "size": 37_733,
    },
    "vader_lexicon": {
        "category": "sentiment",
        "file_name": "vader_lexicon.zip",
        "url": f"https://raw.githubusercontent.com/nltk/nltk_data/{NLTK_DATA_COMMIT}/packages/sentiment/vader_lexicon.zip",
        "sha256": "8adba4294eef3964d820bf655e37e61bdc3a341994356af59b74fb3b4a36ce5c",
        "size": 90_486,
    },
}

PYC_PARSER_COMPAT_TABLES: dict[str, str] = {
    "lextab.py": '''"""Compatibility stub for legacy pycparser table imports.

pycparser 3.x no longer generates or uses PLY lexer tables, but some packaging
hooks still expect this module to exist.
"""

_tabversion = "3.10"
_lextokens = ()
_lexreflags = 0
_lexliterals = ""
_lexstateinfo = {}
_lexstatere = {}
_lexstateignore = {}
_lexstateerrorf = {}
_lexstateeoff = {}
''',
    "yacctab.py": '''"""Compatibility stub for legacy pycparser table imports.

pycparser 3.x no longer generates or uses PLY parser tables, but some packaging
hooks still expect this module to exist.
"""

_tabversion = "3.10"
_lr_method = "LALR"
_lr_signature = ""
_lr_action = {}
_lr_goto = {}
_lr_productions = []
''',
}


def required_nltk_resources() -> tuple[str, ...]:
    return tuple(NLTK_RESOURCE_LOCATIONS.keys())


def pinned_nltk_resource_manifest() -> list[dict[str, str | int]]:
    return [
        {
            "name": name,
            "url": str(asset["url"]),
            "sha256": str(asset["sha256"]),
            "size": int(asset["size"]),
        }
        for name, asset in NLTK_RESOURCE_ASSETS.items()
    ]


def ensure_pycparser_compat_modules(package_dir: Path | str) -> list[Path]:
    package_path = Path(package_dir)
    if not (package_path / "__init__.py").exists():
        raise ValueError(f"Expected a pycparser package directory, got: {package_path}")

    written: list[Path] = []
    for file_name, content in PYC_PARSER_COMPAT_TABLES.items():
        target = package_path / file_name
        if not target.exists():
            target.write_text(content, encoding="utf-8")
        written.append(target)
    return written


def ensure_installed_pycparser_compat_modules() -> list[Path]:
    import pycparser

    return ensure_pycparser_compat_modules(Path(pycparser.__file__).resolve().parent)


def _nltk_resource_present(resource: str, search_paths: Iterable[str] | None = None) -> bool:
    import nltk

    for location in NLTK_RESOURCE_LOCATIONS[resource]:
        try:
            nltk.data.find(location, paths=list(search_paths) if search_paths is not None else None)
            return True
        except (LookupError, OSError, zipfile.BadZipFile):
            continue
    return False


def _remove_staged_nltk_resource(target_path: Path, resource: str) -> None:
    for location in NLTK_RESOURCE_LOCATIONS[resource]:
        candidate = target_path / location
        candidates = [candidate]
        if candidate.suffix != ".zip":
            candidates.append(candidate.with_suffix(candidate.suffix + ".zip"))

        for path in candidates:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                path.unlink()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_asset(path: Path, asset: dict[str, str | int]) -> bool:
    if not path.is_file() or path.stat().st_size != int(asset["size"]):
        return False
    return _sha256_file(path) == str(asset["sha256"])


def _download_pinned_asset(resource: str, download_dir: Path) -> Path:
    asset = NLTK_RESOURCE_ASSETS[resource]
    download_dir.mkdir(parents=True, exist_ok=True)
    target = download_dir / str(asset["file_name"])
    if _verified_asset(target, asset):
        return target

    partial = target.with_suffix(target.suffix + ".part")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(
        str(asset["url"]),
        headers={"User-Agent": "EDMG-Studio-release-builder/1.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output)
        if not _verified_asset(partial, asset):
            actual = _sha256_file(partial) if partial.exists() else "missing"
            raise RuntimeError(
                f"Pinned NLTK resource {resource} failed verification: "
                f"expected {asset['sha256']}, got {actual}"
            )
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def _extract_zip_safely(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if target != destination_root and destination_root not in target.parents:
                raise RuntimeError(f"Unsafe path in pinned NLTK archive {archive.name}: {member.filename}")
        bundle.extractall(destination)


def ensure_nltk_resources(target_dir: Path | str, resources: Iterable[str] | None = None) -> list[str]:
    import nltk

    target_path = Path(target_dir)
    target_path.mkdir(parents=True, exist_ok=True)
    download_dir = target_path.parent / "nltk-archives"
    target_str = str(target_path)
    if target_str not in nltk.data.path:
        nltk.data.path.insert(0, target_str)

    requested = tuple(resources or required_nltk_resources())
    for resource in requested:
        if resource not in NLTK_RESOURCE_LOCATIONS:
            raise KeyError(f"Unknown NLTK resource: {resource}")
        asset = NLTK_RESOURCE_ASSETS[resource]
        category_dir = target_path / str(asset["category"])
        staged_archive = category_dir / str(asset["file_name"])
        if _verified_asset(staged_archive, asset) and _nltk_resource_present(resource, [target_str]):
            continue
        _remove_staged_nltk_resource(target_path, resource)
        archive = _download_pinned_asset(resource, download_dir)
        category_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(archive, staged_archive)
        _extract_zip_safely(staged_archive, category_dir)
        if not _nltk_resource_present(resource, [target_str]):
            raise RuntimeError(f"Pinned NLTK resource did not stage correctly: {resource}")
    return list(requested)
