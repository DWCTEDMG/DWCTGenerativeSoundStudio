from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

JOURNAL_SCHEMA_VERSION = 1
JOURNAL_FILENAME = "autosave.journal.json"
SNAPSHOT_DIRNAME = "autosave"


@dataclass
class RecoveryCandidate:
    kind: str
    path: Path
    saved_at: str
    reason: str
    payload: dict[str, Any]


class AutosaveJournal:
    """Crash-safe project journal + recovery snapshots."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.journal_path = project_dir / JOURNAL_FILENAME
        self.snapshot_dir = project_dir / SNAPSHOT_DIRNAME
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def _now(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")

    def _write_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    def write_journal(
        self,
        *,
        project_id: str,
        meta: dict[str, Any],
        reason: str = "autosave",
        dirty: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "project_id": project_id,
            "saved_at": self._now(),
            "reason": str(reason or "autosave"),
            "dirty": bool(dirty),
            "meta": dict(meta or {}),
        }
        self._write_atomic(self.journal_path, payload)
        return payload

    def write_snapshot(
        self,
        *,
        project_id: str,
        meta: dict[str, Any],
        reason: str = "checkpoint",
    ) -> Path:
        stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns()}"
        path = self.snapshot_dir / f"snapshot-{stamp}.json"
        payload = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "project_id": project_id,
            "saved_at": self._now(),
            "reason": str(reason or "checkpoint"),
            "meta": dict(meta or {}),
        }
        self._write_atomic(path, payload)
        # Keep a bounded trail of snapshots.
        snaps = sorted(self.snapshot_dir.glob("snapshot-*.json"), key=lambda p: p.name)
        for old in snaps[:-12]:
            try:
                old.unlink()
            except OSError:
                pass
        return path

    def read_journal(self) -> dict[str, Any] | None:
        if not self.journal_path.exists():
            return None
        try:
            data = json.loads(self.journal_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        return data

    def mark_clean(self) -> None:
        journal = self.read_journal()
        if not journal:
            return
        journal["dirty"] = False
        journal["saved_at"] = self._now()
        journal["reason"] = "persisted"
        self._write_atomic(self.journal_path, journal)

    def clear_journal(self) -> None:
        if self.journal_path.exists():
            self.journal_path.unlink()

    def list_recovery_candidates(self) -> list[RecoveryCandidate]:
        out: list[RecoveryCandidate] = []
        journal = self.read_journal()
        if journal and journal.get("dirty"):
            out.append(
                RecoveryCandidate(
                    kind="journal",
                    path=self.journal_path,
                    saved_at=str(journal.get("saved_at") or ""),
                    reason=str(journal.get("reason") or "autosave"),
                    payload=journal,
                )
            )
        for snap in sorted(self.snapshot_dir.glob("snapshot-*.json"), key=lambda p: p.name, reverse=True):
            try:
                data = json.loads(snap.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            out.append(
                RecoveryCandidate(
                    kind="snapshot",
                    path=snap,
                    saved_at=str(data.get("saved_at") or ""),
                    reason=str(data.get("reason") or "checkpoint"),
                    payload=data,
                )
            )
        return out

    def latest_valid_recovery(self) -> RecoveryCandidate | None:
        for candidate in self.list_recovery_candidates():
            meta = candidate.payload.get("meta")
            if isinstance(meta, dict):
                return candidate
        return None
