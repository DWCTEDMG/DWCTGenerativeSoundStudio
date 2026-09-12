"""Atomic project-scoped persistence for Director review reports."""

from __future__ import annotations

import json
import os
import threading
import uuid
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

from ..domain.director_review import ReviewReport


class DirectorReviewStore:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}

    def _lock(self, project_dir: Path) -> threading.RLock:
        key = str(project_dir.resolve())
        with self._guard:
            return self._locks.setdefault(key, threading.RLock())

    @contextmanager
    def transaction(self, project_dir: Path) -> Iterator[None]:
        with self._lock(project_dir):
            yield

    @staticmethod
    def _directory(project_dir: Path) -> Path:
        root = project_dir.resolve()
        target = (root / "reviews" / "director").resolve()
        target.relative_to(root)
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _index_path(self, project_dir: Path) -> Path:
        return self._directory(project_dir) / "index.json"

    @staticmethod
    def _write_atomic(path: Path, payload: object) -> None:
        temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _read_index(self, project_dir: Path) -> list[dict]:
        path = self._index_path(project_dir)
        if not path.exists():
            return []
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, list):
            raise ValueError("Director review index is invalid")
        return loaded

    def find_by_fingerprint(self, project_dir: Path, fingerprint: str) -> ReviewReport | None:
        for entry in reversed(self._read_index(project_dir)):
            if entry.get("request_fingerprint") == fingerprint:
                return self.get(project_dir, str(entry["report_id"]))
        return None

    def list(self, project_dir: Path) -> list[ReviewReport]:
        return [self.get(project_dir, str(entry["report_id"])) for entry in reversed(self._read_index(project_dir))]

    def get(self, project_dir: Path, report_id: str) -> ReviewReport:
        if not report_id or any(char not in "0123456789abcdef" for char in report_id) or len(report_id) != 64:
            raise KeyError(report_id)
        path = self._directory(project_dir) / f"{report_id}.json"
        if not path.is_file():
            raise KeyError(report_id)
        return ReviewReport.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, project_dir: Path, report: ReviewReport) -> None:
        with self._lock(project_dir):
            directory = self._directory(project_dir)
            self._write_atomic(directory / f"{report.report_id}.json", report.model_dump(mode="json"))
            index = [item for item in self._read_index(project_dir) if item.get("report_id") != report.report_id]
            index.append({"report_id": report.report_id, "request_fingerprint": report.request_fingerprint,
                          "artifact_path": report.artifact_path, "created_at": report.created_at})
            self._write_atomic(self._index_path(project_dir), index[-200:])
