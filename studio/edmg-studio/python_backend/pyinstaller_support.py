from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from typing import Iterable

NLTK_RESOURCE_LOCATIONS: dict[str, tuple[str, ...]] = {
    "punkt": ("tokenizers/punkt",),
    "punkt_tab": ("tokenizers/punkt_tab",),
    "stopwords": ("corpora/stopwords",),
    "vader_lexicon": ("sentiment/vader_lexicon.zip", "sentiment/vader_lexicon"),
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


def _nltk_resource_present(resource: str) -> bool:
    import nltk

    for location in NLTK_RESOURCE_LOCATIONS[resource]:
        try:
            nltk.data.find(location)
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


def ensure_nltk_resources(target_dir: Path | str, resources: Iterable[str] | None = None) -> list[str]:
    import nltk

    target_path = Path(target_dir)
    target_path.mkdir(parents=True, exist_ok=True)
    target_str = str(target_path)
    if target_str not in nltk.data.path:
        nltk.data.path.insert(0, target_str)

    requested = tuple(resources or required_nltk_resources())
    for resource in requested:
        if resource not in NLTK_RESOURCE_LOCATIONS:
            raise KeyError(f"Unknown NLTK resource: {resource}")
        if _nltk_resource_present(resource):
            continue
        _remove_staged_nltk_resource(target_path, resource)
        ok = bool(nltk.download(resource, download_dir=target_str, quiet=True, force=True))
        if not ok or not _nltk_resource_present(resource):
            raise RuntimeError(f"Failed to stage NLTK resource: {resource}")
    return list(requested)
