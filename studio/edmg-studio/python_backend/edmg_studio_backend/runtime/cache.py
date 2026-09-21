"""Content-addressed local engines; manifests are the atomic commit record."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

from ..services.model_load_coordinator import ModelLoadTimeout, model_load_lock

SCHEMA = 1
STATES = {"missing", "building", "validating", "ready", "failed", "stale", "quarantined", "disabled"}


def digest_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def engine_key(identity: dict) -> str:
    return hashlib.sha256(json.dumps({"schema": SCHEMA, **identity}, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class EngineCache:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir).resolve() / "tensorrt"

    def directory(self, key: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ValueError("Invalid engine ID")
        path = self.root / "engines" / key
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("Engine cache path escaped its root")
        return path

    def lock(self, key: str, **kwargs):
        self.directory(key)
        return model_load_lock(self.root / "locks" / key, **kwargs)

    def read(self, key: str) -> dict | None:
        try:
            value = json.loads((self.directory(key) / "manifest.json").read_text())
            return value if isinstance(value, dict) else None
        except (ValueError, OSError):
            return None

    def state(self, key: str, identity: dict, state: str, **detail) -> dict:
        if state not in STATES:
            raise ValueError("Unknown engine state")
        value = {"schema": SCHEMA, "engine_id": key, "identity": identity,
                 "state": state, "updated_at": time.time(), "source": "edmg_local_build", **detail}
        atomic_write(self.directory(key) / "manifest.json", json.dumps(value, allow_nan=False).encode())
        return value

    def lookup(self, identity: dict) -> tuple[Path, dict] | None:
        key = engine_key(identity)
        manifest = self.read(key)
        if not manifest or manifest.get("state") != "ready":
            return None
        path = self.directory(key) / "engine.plan"
        try:
            valid = (manifest.get("schema") == SCHEMA and manifest.get("engine_id") == key
                     and manifest.get("identity") == identity
                     and manifest.get("source") == "edmg_local_build"
                     and manifest.get("validation", {}).get("passed") is True
                     and path.is_file() and not path.is_symlink()
                     and digest_file(path) == manifest.get("engine_sha256"))
        except OSError:
            valid = False
        if not valid:
            self.quarantine(key, "Engine identity, validation receipt or checksum mismatch")
            return None
        os.utime(path, None)
        return path, manifest

    def publish(self, identity: dict, engine: bytes, validation: dict, benchmark: dict) -> dict:
        if validation.get("passed") is not True:
            raise ValueError("Unvalidated engines cannot be published")
        key = engine_key(identity)
        atomic_write(self.directory(key) / "engine.plan", engine)
        return self.state(key, identity, "ready", engine_sha256=hashlib.sha256(engine).hexdigest(),
                          validation=validation, benchmark=benchmark, size_bytes=len(engine))

    def quarantine(self, key: str, reason: str) -> None:
        source = self.directory(key)
        old = self.read(key) or {}
        engine = source / "engine.plan"
        if engine.is_file():
            target = self.root / "quarantine" / f"{key}-{time.time_ns()}.plan"
            target.parent.mkdir(parents=True, exist_ok=True)
            engine.replace(target)
        self.state(key, old.get("identity", {}), "quarantined", reason=reason)

    def entries(self) -> list[dict]:
        result = []
        for path in (self.root / "engines").glob("*/manifest.json"):
            if re.fullmatch(r"[0-9a-f]{64}", path.parent.name):
                value = self.read(path.parent.name)
                if value:
                    result.append(value)
        return result

    def clear(self, key: str) -> None:
        with self.lock(key, timeout_s=0):
            directory = self.directory(key)
            # Only our two artifacts; never recursively remove a model directory.
            (directory / "manifest.json").unlink(missing_ok=True)
            (directory / "engine.plan").unlink(missing_ok=True)

    def trim(self, limit_bytes: int, *, keep: str = "") -> None:
        files = sorted((self.root / "engines").glob("*/engine.plan"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        for path in files:
            if total <= limit_bytes:
                break
            if path.parent.name == keep:
                continue
            size = path.stat().st_size
            try:
                self.clear(path.parent.name)
                total -= size
            except ModelLoadTimeout:
                continue
