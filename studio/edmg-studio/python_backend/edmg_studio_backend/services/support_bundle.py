from __future__ import annotations

import io
import json
import re
import stat
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

_ALLOWED_SUFFIXES = {".json", ".jsonl", ".log", ".txt"}
_PRIVATE_MEDIA_SUFFIXES = {
    ".aac", ".aif", ".aiff", ".avi", ".bmp", ".flac", ".gif", ".jpeg", ".jpg",
    ".m4a", ".mkv", ".mov", ".mp3", ".mp4", ".ogg", ".png", ".wav", ".webm",
}
_SECRET_KEY_RE = re.compile(
    r"(?:api[_-]?key|authorization|cookie|credential|password|secret|token)", re.IGNORECASE
)
_TEXT_SECRET_RE = re.compile(
    r"(?im)(\b(?:api[_-]?key|authorization|cookie|password|secret|token)\b\s*[:=]\s*)([^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_WINDOWS_ABSOLUTE_RE = re.compile(r"(?i)(?<![\w])(?:[a-z]:\\|\\\\)[^\r\n\t\"']+")
_POSIX_ABSOLUTE_RE = re.compile(r"(?<![\w.])/(?:[^\s/]+/)+[^\s,;\"']*")


@dataclass(frozen=True)
class DiagnosticRoot:
    name: str
    path: Path


@dataclass(frozen=True)
class BundleLimits:
    max_files: int = 200
    max_file_bytes: int = 1_000_000
    max_total_bytes: int = 10_000_000


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SECRET_KEY_RE.search(str(key)) else _redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(value: str) -> str:
    value = _BEARER_RE.sub("Bearer [REDACTED]", value)
    value = _TEXT_SECRET_RE.sub(r"\1[REDACTED]", value)
    value = _WINDOWS_ABSOLUTE_RE.sub("[LOCAL_PATH]", value)
    return _POSIX_ABSOLUTE_RE.sub("[LOCAL_PATH]", value)


def _safe_text(path: Path, raw: bytes) -> bytes:
    text = raw.decode("utf-8", errors="replace")
    if path.suffix.lower() == ".json":
        try:
            payload = _redact_value(json.loads(text))
            return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        except (TypeError, ValueError):
            pass
    if path.suffix.lower() == ".jsonl":
        lines: list[str] = []
        for line in text.splitlines():
            try:
                lines.append(json.dumps(_redact_value(json.loads(line)), sort_keys=True))
            except (TypeError, ValueError):
                lines.append(redact_text(line))
        return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    return redact_text(text).encode("utf-8")


def build_support_bundle(
    roots: Iterable[DiagnosticRoot],
    *,
    limits: BundleLimits = BundleLimits(),
) -> bytes:
    included: list[dict[str, Any]] = []
    omitted: list[dict[str, str]] = []
    collected: list[tuple[str, bytes]] = []
    total_bytes = 0

    def omit(member: str, reason: str) -> None:
        omitted.append({"path": member, "reason": reason})

    for root in roots:
        root_path = root.path
        if not root_path.exists():
            omit(root.name, "missing_root")
            continue
        if root_path.is_symlink() or not root_path.is_dir():
            omit(root.name, "unsafe_root")
            continue
        pending = [root_path]
        while pending:
            directory = pending.pop()
            try:
                entries = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
            except OSError:
                omit(f"{root.name}/{directory.relative_to(root_path).as_posix()}", "unreadable")
                continue
            for path in entries:
                relative = path.relative_to(root_path)
                member = str(PurePosixPath(root.name, *relative.parts))
                try:
                    mode = path.lstat().st_mode
                except OSError:
                    omit(member, "unreadable")
                    continue
                if stat.S_ISLNK(mode):
                    omit(member, "symlink")
                elif stat.S_ISDIR(mode):
                    pending.append(path)
                elif not stat.S_ISREG(mode):
                    omit(member, "non_regular")
                elif path.suffix.lower() in _PRIVATE_MEDIA_SUFFIXES:
                    omit(member, "private_media")
                elif path.suffix.lower() not in _ALLOWED_SUFFIXES:
                    omit(member, "file_type")
                elif len(collected) >= limits.max_files:
                    omit(member, "file_count")
                else:
                    try:
                        size = path.stat().st_size
                        if size > limits.max_file_bytes:
                            omit(member, "file_size")
                            continue
                        if total_bytes + size > limits.max_total_bytes:
                            omit(member, "total_size")
                            continue
                        content = _safe_text(path, path.read_bytes())
                    except OSError:
                        omit(member, "unreadable")
                        continue
                    if total_bytes + len(content) > limits.max_total_bytes:
                        omit(member, "total_size")
                        continue
                    collected.append((member, content))
                    total_bytes += len(content)
                    included.append({"path": member, "bytes": len(content)})

    manifest = {
        "schema_version": 1,
        "disclosure": "Allowlisted text diagnostics only; secrets and local absolute paths are redacted.",
        "included": included,
        "omitted": omitted,
        "limits": {
            "max_files": limits.max_files,
            "max_file_bytes": limits.max_file_bytes,
            "max_total_bytes": limits.max_total_bytes,
        },
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member, content in collected:
            archive.writestr(member, content)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return output.getvalue()
