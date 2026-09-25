from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..render_profiles import (
    ProjectRenderProfile,
    accept_render_payload,
    accepted_render_request_matches,
    is_render_job_type,
    retain_accepted_render_snapshot,
)

logger = logging.getLogger(__name__)

Status = Literal["queued", "paused", "running", "succeeded", "failed", "canceled"]

# Renamed aside when a project tree is unreadable (e.g. WinError 1392 on USB).
_CORRUPTED_QUARANTINE_SUFFIX = ".__corrupted_quarantine"


def _quarantine_unreadable_project(proj_dir: Path) -> Path | None:
    """Best-effort rename of a corrupted project folder so later scans skip it."""
    name = proj_dir.name
    if name.endswith(_CORRUPTED_QUARANTINE_SUFFIX):
        return None
    target = proj_dir.with_name(f"{name}{_CORRUPTED_QUARANTINE_SUFFIX}")
    try:
        if target.exists():
            target = proj_dir.with_name(f"{name}.{int(time.time())}{_CORRUPTED_QUARANTINE_SUFFIX}")
    except OSError:
        target = proj_dir.with_name(f"{name}.{int(time.time())}{_CORRUPTED_QUARANTINE_SUFFIX}")
    try:
        proj_dir.rename(target)
        logger.warning("Quarantined unreadable project directory: %s -> %s", proj_dir, target)
        return target
    except OSError as exc:
        logger.warning("Could not quarantine unreadable project %s: %s", proj_dir, exc)
        return None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    result_json TEXT,
    error TEXT,
    progress_json TEXT,
    lease_owner TEXT,
    lease_expires_at REAL,
    attempt INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT,
    execution_json TEXT,
    PRIMARY KEY (project_id, id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at, id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idempotency
    ON jobs(project_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS job_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    detail_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_job_events_job ON job_events(project_id, job_id, event_id);
CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    applied_at TEXT NOT NULL
);
"""

_JOB_SCHEMA_MIGRATIONS = (
    (1, "jobs-priority-and-queue-order"),
    (2, "jobs-execution-resolution"),
)


@dataclass
class Job:
    id: str
    project_id: str
    type: str
    status: Status
    created_at: str
    updated_at: str
    payload: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    progress: dict[str, Any] | None = None
    attempt: int = 0
    priority: int = 0
    idempotency_key: str | None = None
    execution: dict[str, Any] | None = None


@dataclass
class JobRegistration:
    job: Job | None
    cancel_requested: bool = False

    @property
    def active(self) -> bool:
        return self.job is not None and self.job.status in ("queued", "running")

    def cancel(self) -> None:
        self.cancel_requested = True


class JobStore:
    """SQLite-backed job/event store with JSON compatibility migration."""

    def __init__(self, projects_dir: Path, *, db_path: Path | None = None):
        self.projects_dir = projects_dir
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path or (self.projects_dir.parent / "jobs.sqlite")
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        with self._conn:
            self._conn.executescript(_SCHEMA)
            self._migrate_schema()
        self._migrate_json_jobs()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _project_render_profile(self, project_id: str) -> ProjectRenderProfile | None:
        try:
            document = json.loads((self.projects_dir / project_id / "project.json").read_text(encoding="utf-8"))
            profile = (document.get("meta") or {}).get("render_profile")
            return ProjectRenderProfile.model_validate(profile) if isinstance(profile, dict) else None
        except (OSError, ValueError, TypeError):
            return None

    def _accepted_payload(self, project_id: str, job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not is_render_job_type(job_type):
            return payload
        return accept_render_payload(payload, render_profile=self._project_render_profile(project_id))

    def _migrate_schema(self) -> None:
        applied = {
            int(row[0])
            for row in self._conn.execute("SELECT migration_id FROM schema_migrations").fetchall()
        }
        for migration_id, name in _JOB_SCHEMA_MIGRATIONS:
            if migration_id in applied:
                continue
            if migration_id == 1:
                columns = {
                    str(row["name"])
                    for row in self._conn.execute("PRAGMA table_info(jobs)").fetchall()
                }
                if "priority" not in columns:
                    self._conn.execute(
                        "ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"
                    )
                self._conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_jobs_queue_order
                    ON jobs(status, priority DESC, created_at ASC, id ASC)
                    """
                )
            elif migration_id == 2:
                columns = {
                    str(row["name"])
                    for row in self._conn.execute("PRAGMA table_info(jobs)").fetchall()
                }
                if "execution_json" not in columns:
                    self._conn.execute("ALTER TABLE jobs ADD COLUMN execution_json TEXT")
            self._conn.execute(
                "INSERT INTO schema_migrations(migration_id, name, applied_at) VALUES (?, ?, ?)",
                (migration_id, name, self._now()),
            )

    def _jobs_dir(self, project_id: str) -> Path:
        d = self.projects_dir / project_id / "jobs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _now(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            project_id=row["project_id"],
            type=row["type"],
            status=row["status"],  # type: ignore[arg-type]
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            payload=json.loads(row["payload_json"] or "{}"),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=row["error"],
            progress=json.loads(row["progress_json"]) if row["progress_json"] else None,
            attempt=int(row["attempt"] or 0),
            priority=int(row["priority"] or 0),
            idempotency_key=row["idempotency_key"],
            execution=(
                json.loads(row["execution_json"])
                if "execution_json" in row.keys() and row["execution_json"]
                else None
            ),
        )

    def _record_event(self, project_id: str, job_id: str, event_type: str, detail: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO job_events(project_id, job_id, event_type, created_at, detail_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, job_id, event_type, self._now(), json.dumps(detail, ensure_ascii=False)),
        )

    def _upsert_job(self, job: Job) -> None:
        self._conn.execute(
            """
            INSERT INTO jobs(
                id, project_id, type, status, created_at, updated_at,
                payload_json, result_json, error, progress_json,
                lease_owner, lease_expires_at, attempt, priority, idempotency_key,
                execution_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?)
            ON CONFLICT(project_id, id) DO UPDATE SET
                type=excluded.type,
                status=excluded.status,
                updated_at=excluded.updated_at,
                payload_json=excluded.payload_json,
                result_json=excluded.result_json,
                error=excluded.error,
                progress_json=excluded.progress_json,
                attempt=excluded.attempt,
                priority=excluded.priority,
                idempotency_key=excluded.idempotency_key
                ,execution_json=excluded.execution_json
            WHERE jobs.status IN ('queued', 'paused', 'running')
              AND jobs.attempt = excluded.attempt
            """,
            (
                job.id,
                job.project_id,
                job.type,
                job.status,
                job.created_at,
                job.updated_at,
                json.dumps(job.payload or {}, ensure_ascii=False),
                json.dumps(job.result, ensure_ascii=False) if job.result is not None else None,
                job.error,
                json.dumps(job.progress, ensure_ascii=False) if job.progress is not None else None,
                int(job.attempt or 0),
                int(job.priority or 0),
                job.idempotency_key,
                json.dumps(job.execution, ensure_ascii=False) if job.execution is not None else None,
            ),
        )

    def _migrate_json_jobs(self) -> None:
        try:
            if not self.projects_dir.exists():
                return
            proj_dirs = list(self.projects_dir.iterdir())
        except OSError as exc:
            logger.warning(
                "Cannot scan projects directory for job migration: %s (%s)",
                self.projects_dir,
                exc,
            )
            return

        for proj_dir in proj_dirs:
            if proj_dir.name.endswith(_CORRUPTED_QUARANTINE_SUFFIX):
                continue
            try:
                # WinError 1392 (corrupt/unreadable) can raise from is_dir/exists/glob
                # on flaky USB/external volumes — never abort backend startup for one project.
                if not proj_dir.is_dir():
                    continue
                jobs_dir = proj_dir / "jobs"
                if not jobs_dir.exists():
                    continue
                job_paths = list(jobs_dir.glob("*.json"))
            except OSError as exc:
                logger.warning(
                    "Skipping corrupted project during job migration: %s (%s)",
                    proj_dir,
                    exc,
                )
                _quarantine_unreadable_project(proj_dir)
                continue

            for jpath in job_paths:
                try:
                    data = json.loads(jpath.read_text(encoding="utf-8"))
                    job = Job(
                        id=str(data["id"]),
                        project_id=str(data.get("project_id") or proj_dir.name),
                        type=str(data.get("type") or "unknown"),
                        status=str(data.get("status") or "queued"),  # type: ignore[arg-type]
                        created_at=str(data.get("created_at") or self._now()),
                        updated_at=str(data.get("updated_at") or self._now()),
                        payload=dict(data.get("payload") or {}),
                        result=data.get("result"),
                        error=data.get("error"),
                        progress=data.get("progress"),
                        attempt=int(data.get("attempt") or 0),
                        execution=(dict(data["execution"]) if isinstance(data.get("execution"), dict) else None),
                        priority=int(data.get("priority") or 0),
                        idempotency_key=data.get("idempotency_key"),
                    )
                except Exception:
                    continue
                existing = self.get(job.project_id, job.id)
                if existing is None:
                    with self._lock:
                        self._upsert_job(job)
                        self._record_event(
                            job.project_id,
                            job.id,
                            "migrated_from_json",
                            {"path": str(jpath)},
                        )
                        self._conn.commit()

    def create(
        self,
        project_id: str,
        job_type: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        priority: int = 0,
    ) -> Job:
        job, _ = self.create_with_status(
            project_id,
            job_type,
            payload,
            idempotency_key=idempotency_key,
            priority=priority,
        )
        return job

    def create_with_status(
        self,
        project_id: str,
        job_type: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        priority: int = 0,
    ) -> tuple[Job, bool]:
        key = str(idempotency_key or "").strip() or None
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                if key:
                    row = self._conn.execute(
                        """
                        SELECT * FROM jobs
                        WHERE project_id = ? AND idempotency_key = ?
                        LIMIT 1
                        """,
                        (project_id, key),
                    ).fetchone()
                    if row is not None:
                        self._conn.commit()
                        existing = self._row_to_job(row)
                        self._mirror_json(existing)
                        return existing, False
                accepted_payload = self._accepted_payload(project_id, job_type, payload)
                jid = uuid.uuid4().hex
                now = self._now()
                job = Job(
                    id=jid,
                    project_id=project_id,
                    type=job_type,
                    status="queued",
                    created_at=now,
                    updated_at=now,
                    payload=accepted_payload,
                    priority=priority,
                    idempotency_key=key,
                )
                self._upsert_job(job)
                self._record_event(project_id, jid, "created", {"type": job_type})
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise
            # Keep a JSON mirror for older tooling that reads jobs/*.json.
            self._mirror_json(job)
            return job, True

    def create_batch_with_status(
        self,
        project_id: str,
        requests: list[tuple[str, dict[str, Any], str | None, int]],
    ) -> list[tuple[Job, bool]]:
        """Atomically validate idempotent replays and create all missing jobs."""
        results: list[tuple[Job, bool]] = []
        created_jobs: list[Job] = []
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                for job_type, payload, idempotency_key, priority in requests:
                    key = str(idempotency_key or "").strip() or None
                    accepted_payload = self._accepted_payload(project_id, job_type, payload)
                    row = None
                    if key:
                        row = self._conn.execute(
                            """
                            SELECT * FROM jobs
                            WHERE project_id = ? AND idempotency_key = ?
                            LIMIT 1
                            """,
                            (project_id, key),
                        ).fetchone()
                    if row is not None:
                        existing = self._row_to_job(row)
                        if existing.type != job_type or not accepted_render_request_matches(existing.payload, payload):
                            raise ValueError("Idempotency key already used for a different job request")
                        results.append((existing, False))
                        continue

                    jid = uuid.uuid4().hex
                    now = self._now()
                    job = Job(
                        id=jid,
                        project_id=project_id,
                        type=job_type,
                        status="queued",
                        created_at=now,
                        updated_at=now,
                        payload=accepted_payload,
                        priority=priority,
                        idempotency_key=key,
                    )
                    self._upsert_job(job)
                    self._record_event(project_id, jid, "created", {"type": job_type})
                    results.append((job, True))
                    created_jobs.append(job)
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

            for job, _created in results:
                self._mirror_json(job)
            return results

    def _mirror_json(self, job: Job) -> None:
        try:
            path = self._jobs_dir(job.project_id) / f"{job.id}.json"
            path.write_text(json.dumps(job.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning(
                "Could not update compatibility job mirror for %s/%s: %s",
                job.project_id,
                job.id,
                exc,
            )

    def save(self, job: Job) -> None:
        with self._lock:
            job.updated_at = self._now()
            self._upsert_job(job)
            persisted = self.get(job.project_id, job.id)
            if persisted is not None and persisted.attempt != job.attempt:
                # Do not turn an obsolete worker's mutable handle into the new
                # attempt: a later save from that worker must stay fenced out.
                self._conn.commit()
                return
            if persisted is not None:
                job.__dict__.update(persisted.__dict__)
            self._record_event(
                job.project_id,
                job.id,
                "saved",
                {"status": job.status},
            )
            self._conn.commit()
            self._mirror_json(job)

    @contextmanager
    def registration_guard(self, project_id: str, job_id: str):
        """Serialize project registration and cancellation with worker publication."""
        mirrored: Job | None = None
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT * FROM jobs WHERE project_id = ? AND id = ?",
                    (project_id, job_id),
                ).fetchone()
                registration = JobRegistration(self._row_to_job(row) if row else None)
                yield registration
                if registration.cancel_requested and registration.active:
                    registration.job.status = "canceled"
                    registration.job.updated_at = self._now()
                    self._upsert_job(registration.job)
                    self._record_event(project_id, job_id, "canceled", {})
                    mirrored = registration.job
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise
        if mirrored is not None:
            self._mirror_json(mirrored)

    @contextmanager
    def publication_guard(self, project_id: str, job_id: str, *, attempt: int | None = None):
        """Serialize publication with cancellation across worker processes."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                current = self.get(project_id, job_id)
                yield bool(
                    current and current.status in ("queued", "running")
                    and (attempt is None or current.attempt == attempt)
                )
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    def get(self, project_id: str, job_id: str) -> Job | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE project_id = ? AND id = ?",
                (project_id, job_id),
            ).fetchone()
        return self._row_to_job(row) if row else None

    def log_path(self, project_id: str, job_id: str) -> Path:
        return self._jobs_dir(project_id) / f"{job_id}.log"

    def append_log(self, project_id: str, job_id: str, line: str) -> None:
        lp = self.log_path(project_id, job_id)
        ts = time.strftime("%H:%M:%S")
        lp.parent.mkdir(parents=True, exist_ok=True)
        with lp.open("a", encoding="utf-8") as f:
            f.write(f"[{ts}] {line.rstrip()}\n")
        with self._lock:
            self._record_event(project_id, job_id, "log", {"line": line})
            self._conn.commit()

    def update_progress(
        self,
        project_id: str,
        job_id: str,
        *,
        stage: str,
        current: int,
        total: int,
        message: str | None = None,
        extra: dict[str, Any] | None = None,
        expected_attempt: int | None = None,
    ) -> Job | None:
        job = self.get(project_id, job_id)
        if not job or (expected_attempt is not None and job.attempt != expected_attempt):
            return None
        total_i = max(1, int(total))
        current_i = max(0, min(int(current), total_i))
        pct = max(0.0, min(100.0, (float(current_i) / float(total_i)) * 100.0))
        progress = {
            "stage": str(stage or "running"),
            "current": current_i,
            "total": total_i,
            "percent": round(pct, 1),
        }
        if message:
            progress["message"] = str(message)
        if extra:
            progress.update(extra)
        job.progress = progress
        self.save(job)
        return job

    def list_for_project(self, project_id: str) -> list[Job]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM jobs
                WHERE project_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def cancel(self, project_id: str, job_id: str) -> Job | None:
        job = self.get(project_id, job_id)
        if not job:
            return None
        if job.status in ("succeeded", "failed", "canceled"):
            return job
        job.status = "canceled"
        if isinstance(job.progress, dict):
            total = max(1, int(job.progress.get("total", 1) or 1))
            current = max(0, min(int(job.progress.get("current", 0) or 0), total))
            job.progress = {
                **job.progress,
                "stage": "canceled",
                "current": current,
                "total": total,
                "percent": round(max(0.0, min(100.0, (float(current) / float(total)) * 100.0)), 1),
                "message": "Cancel requested — waiting for current step to finish",
            }
        self.save(job)
        if job.status == "canceled":
            self.append_log(project_id, job_id, "Job canceled")
        return job

    def _transition_status(
        self,
        project_id: str,
        job_id: str,
        *,
        expected_status: Status,
        next_status: Status,
        event_type: str,
    ) -> Job | None:
        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE jobs
                SET status = ?,
                    updated_at = ?,
                    lease_owner = NULL,
                    lease_expires_at = NULL
                WHERE project_id = ? AND id = ? AND status = ?
                """,
                (next_status, self._now(), project_id, job_id, expected_status),
            )
            transitioned = cursor.rowcount == 1
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE project_id = ? AND id = ?",
                (project_id, job_id),
            ).fetchone()
            if row is None:
                self._conn.commit()
                return None
            if transitioned:
                self._record_event(
                    project_id,
                    job_id,
                    event_type,
                    {"from_status": expected_status, "to_status": next_status},
                )
            self._conn.commit()
            job = self._row_to_job(row)
        if transitioned:
            self._mirror_json(job)
        return job

    def pause(self, project_id: str, job_id: str) -> Job | None:
        return self._transition_status(
            project_id,
            job_id,
            expected_status="queued",
            next_status="paused",
            event_type="paused",
        )

    def resume(self, project_id: str, job_id: str) -> Job | None:
        return self._transition_status(
            project_id,
            job_id,
            expected_status="paused",
            next_status="queued",
            event_type="resumed",
        )

    def retry(
        self,
        project_id: str,
        job_id: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> Job | None:
        """Atomically requeue a terminal job while retaining its accepted render snapshot."""

        with self._lock:
            existing_row = self._conn.execute(
                "SELECT * FROM jobs WHERE project_id = ? AND id = ?",
                (project_id, job_id),
            ).fetchone()
            if existing_row is None:
                return None
            existing = self._row_to_job(existing_row)
            replacement = payload if payload is not None else existing.payload
            retained_payload = retain_accepted_render_snapshot(existing.payload, replacement)
            payload_json = json.dumps(retained_payload, ensure_ascii=False) if payload is not None else None
            cursor = self._conn.execute(
                """
                UPDATE jobs
                SET status = 'queued',
                    updated_at = ?,
                    payload_json = COALESCE(?, payload_json),
                    result_json = NULL,
                    error = NULL,
                    progress_json = NULL,
                    execution_json = NULL,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    attempt = attempt + 1
                WHERE project_id = ?
                  AND id = ?
                  AND status IN ('succeeded', 'failed', 'canceled')
                """,
                (self._now(), payload_json, project_id, job_id),
            )
            if cursor.rowcount != 1:
                self._conn.commit()
                return None
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE project_id = ? AND id = ?",
                (project_id, job_id),
            ).fetchone()
            if row is None:  # pragma: no cover - guarded by the successful update
                self._conn.rollback()
                return None
            self._record_event(
                project_id,
                job_id,
                "retried",
                {"to_status": "queued"},
            )
            self._conn.commit()
            job = self._row_to_job(row)
        self._mirror_json(job)
        self.append_log(project_id, job_id, "Job retried (re-queued)")
        return job

    def list_all(self) -> list[Job]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM jobs
                ORDER BY created_at DESC, id DESC
                """
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def set_priority(self, project_id: str, job_id: str, priority: int) -> Job | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT priority FROM jobs WHERE project_id = ? AND id = ?",
                (project_id, job_id),
            ).fetchone()
            if row is None:
                return None
            previous = int(row["priority"] or 0)
            cursor = self._conn.execute(
                """
                UPDATE jobs SET priority = ?, updated_at = ?
                WHERE project_id = ? AND id = ? AND status IN ('queued', 'paused')
                """,
                (int(priority), self._now(), project_id, job_id),
            )
            if cursor.rowcount != 1:
                self._conn.commit()
                return None
            self._record_event(
                project_id,
                job_id,
                "priority_changed",
                {"from_priority": previous, "to_priority": int(priority)},
            )
            updated = self._conn.execute(
                "SELECT * FROM jobs WHERE project_id = ? AND id = ?",
                (project_id, job_id),
            ).fetchone()
            self._conn.commit()
            job = self._row_to_job(updated)
        self._mirror_json(job)
        return job

    def next_queued(self) -> Job | None:
        """Compatibility helper. Prefer claim_next_queued() in worker loops."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM jobs
                WHERE status = 'queued'
                ORDER BY priority DESC, created_at ASC, id ASC
                LIMIT 1
                """
            ).fetchone()
        return self._row_to_job(row) if row else None

    def claim_next_queued(self, *, lease_seconds: float = 300.0, owner: str | None = None) -> Job | None:
        """Atomically claim the next queued job with a lease."""
        claim_owner = owner or f"worker-{uuid.uuid4().hex[:8]}"
        now = time.time()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                # Re-queue expired leases so interrupted workers can recover.
                self._conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'queued',
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?
                    WHERE status = 'running'
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at < ?
                    """,
                    (self._now(), now),
                )
                row = self._conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status = 'queued'
                    ORDER BY priority DESC, created_at ASC, id ASC
                    LIMIT 1
                    """
                ).fetchone()
                if row is None:
                    self._conn.commit()
                    return None
                job = self._row_to_job(row)
                latest = self.get(job.project_id, job.id)
                if not latest or latest.status != "queued":
                    self._conn.commit()
                    return None
                latest.status = "running"
                latest.updated_at = self._now()
                lease_update = self._conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'running',
                        updated_at = ?,
                        lease_owner = ?,
                        lease_expires_at = ?,
                        attempt = attempt + 1
                    WHERE project_id = ? AND id = ? AND status = 'queued'
                    """,
                    (
                        latest.updated_at,
                        claim_owner,
                        now + float(lease_seconds),
                        latest.project_id,
                        latest.id,
                    ),
                )
                if lease_update.rowcount != 1:
                    self._conn.commit()
                    return None
                latest.attempt = int(latest.attempt or 0) + 1
                self._record_event(
                    latest.project_id,
                    latest.id,
                    "claimed",
                    {"owner": claim_owner, "lease_seconds": lease_seconds},
                )
                self._conn.commit()
                self._mirror_json(latest)
                return latest
            except Exception:
                self._conn.rollback()
                raise

    def renew_lease(self, job: Job, *, lease_seconds: float = 300.0) -> bool:
        """Renew only the still-running attempt, without replacing job progress."""
        duration = float(lease_seconds)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Job lease duration must be finite and positive")
        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE jobs SET lease_expires_at = ?
                WHERE project_id = ? AND id = ? AND attempt = ?
                  AND status = 'running' AND lease_owner IS NOT NULL
                """,
                (time.time() + duration, job.project_id, job.id, job.attempt),
            )
            self._conn.commit()
            return cursor.rowcount == 1

    @contextmanager
    def maintain_lease(self, job: Job, *, lease_seconds: float = 300.0):
        """Keep a claimed attempt leased while it waits, renders or shuts down."""
        stopped = threading.Event()
        if not self.renew_lease(job, lease_seconds=lease_seconds):
            yield
            return
        # Capture identity rather than a mutable Job that publication may reload.
        leased = Job(**job.__dict__)

        def heartbeat() -> None:
            while not stopped.wait(min(30.0, float(lease_seconds) / 3)):
                try:
                    if not self.renew_lease(leased, lease_seconds=lease_seconds):
                        return
                except Exception:
                    logger.exception("Could not renew job lease: %s/%s", leased.project_id, leased.id)

        thread = threading.Thread(target=heartbeat, name=f"edmg-lease-{job.id}", daemon=True)
        thread.start()
        try:
            yield
        finally:
            stopped.set()
            thread.join(timeout=5.0)

    def list_events(self, project_id: str, job_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT event_id, event_type, created_at, detail_json
                FROM job_events
                WHERE project_id = ? AND job_id = ?
                ORDER BY event_id ASC
                """,
                (project_id, job_id),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "event_id": row["event_id"],
                    "event_type": row["event_type"],
                    "created_at": row["created_at"],
                    "detail": json.loads(row["detail_json"] or "{}"),
                }
            )
        return out
