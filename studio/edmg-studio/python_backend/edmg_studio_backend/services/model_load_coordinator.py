"""Cross-process admission for queued local model workers.

Model workers run in separate processes so a large Director or video load does
not block the API.  A process-local lock alone is therefore insufficient: two
workers can still load competing models at the same time and exhaust VRAM or
system commit. The dispatcher uses one lock root for all local model job types,
independent of the individual models' directories.

The parent holds the lock until its child exits, including cancellation cleanup.
Model adapters in that child must not acquire the parent's lock again. This is
worker admission, not a claim of hardware qualification or control over external
applications that also use the GPU.
"""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence
from weakref import WeakValueDictionary


class ModelLoadCanceled(RuntimeError):
    """Raised when a waiting model load is canceled before it acquires the lock."""


class ModelLoadTimeout(RuntimeError):
    """Raised when a model load cannot acquire the shared lock in time."""


@dataclass(frozen=True)
class GpuLease:
    device_ids: tuple[str, ...]
    job_id: str
    attempt: int
    owner_token: str
    metadata_paths: tuple[Path, ...]


@dataclass
class _HeldGpuLock:
    lock_path: Path
    thread_lock: threading.Lock
    thread_acquired: bool = False
    fd: int | None = None
    file_acquired: bool = False


_THREAD_LOCKS: WeakValueDictionary[str, threading.Lock] = WeakValueDictionary()
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock_for(path: Path) -> threading.Lock:
    key = os.path.normcase(str(path))
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[key] = lock
        return lock


def _try_file_lock(fd: int) -> bool:
    """Try to acquire byte zero of ``fd`` without blocking."""

    os.lseek(fd, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                return False
            raise

    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            return False
        raise


def _unlock_file(fd: int) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_UN)


def _deadline(timeout_s: float | None) -> float | None:
    if timeout_s is None:
        return None
    timeout = float(timeout_s)
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("Model worker timeout must be finite and nonnegative")
    return time.monotonic() + timeout


def _gpu_lease_root() -> Path:
    configured = os.environ.get("EDMG_GPU_LEASE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(tempfile.gettempdir()) / "DWCT" / "EDMG Studio" / "gpu-leases").resolve()


def _gpu_lock_stem(device_id: str) -> str:
    digest = hashlib.sha256(device_id.encode("utf-8")).hexdigest()[:24]
    return f"gpu-{digest}"


def _write_gpu_metadata(path: Path, payload: dict[str, object], owner_token: str) -> None:
    temporary = path.with_name(f"{path.name}.{owner_token}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _remove_owned_gpu_metadata(path: Path, owner_token: str) -> None:
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(current, dict) and current.get("owner_token") == owner_token:
            path.unlink(missing_ok=True)
    except (OSError, ValueError, TypeError):
        return


@contextmanager
def gpu_execution_lease(
    device_ids: Sequence[str],
    *,
    job_id: str,
    attempt: int,
    cancel_check: Callable[[], bool],
    timeout_seconds: float,
    on_wait: Callable[[], None] | None = None,
    poll_seconds: float = 0.1,
) -> Iterator[GpuLease]:
    """Lease physical GPUs across Windows and WSL worker processes.

    Device IDs are stable reconciled identities, not environment-local CUDA
    indices. Advisory OS locks provide crash recovery; JSON files are diagnostic
    owner metadata and never decide whether a lease is available.
    """

    normalized = tuple(sorted(str(device_id).strip() for device_id in device_ids))
    if not normalized or any(not device_id for device_id in normalized):
        raise ValueError("At least one non-empty physical GPU device ID is required")
    if len(normalized) != len(set(normalized)):
        raise ValueError("Physical GPU device IDs must be unique")
    selected_job = str(job_id).strip()
    if not selected_job:
        raise ValueError("GPU lease job_id is required")
    selected_attempt = int(attempt)
    if selected_attempt < 0:
        raise ValueError("GPU lease attempt must be nonnegative")
    interval = float(poll_seconds)
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("GPU lease poll interval must be finite and positive")
    deadline = _deadline(timeout_seconds)
    root = _gpu_lease_root()
    root.mkdir(parents=True, exist_ok=True)
    owner_token = uuid.uuid4().hex
    held: list[_HeldGpuLock] = []
    metadata_paths: list[Path] = []
    notified = False

    def check_canceled() -> None:
        if cancel_check():
            raise ModelLoadCanceled("GPU execution canceled before lease admission")

    def wait() -> None:
        nonlocal notified
        check_canceled()
        if not notified and on_wait is not None:
            notified = True
            on_wait()
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            raise ModelLoadTimeout("Timed out waiting for the requested physical GPU lease")
        time.sleep(interval if remaining is None else min(interval, remaining))

    try:
        for device_id in normalized:
            lock_path = root / f"{_gpu_lock_stem(device_id)}.lock"
            item = _HeldGpuLock(lock_path=lock_path, thread_lock=_thread_lock_for(lock_path))
            held.append(item)
            while not item.thread_acquired:
                check_canceled()
                item.thread_acquired = item.thread_lock.acquire(blocking=False)
                if not item.thread_acquired:
                    wait()
            item.fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
            while not item.file_acquired:
                check_canceled()
                item.file_acquired = _try_file_lock(item.fd)
                if not item.file_acquired:
                    wait()

        check_canceled()
        acquired_at = datetime.now(UTC).isoformat()
        for device_id in normalized:
            metadata_path = root / f"{_gpu_lock_stem(device_id)}.json"
            _write_gpu_metadata(
                metadata_path,
                {
                    "schema_version": 1,
                    "device_id": device_id,
                    "job_id": selected_job,
                    "attempt": selected_attempt,
                    "pid": os.getpid(),
                    "owner_token": owner_token,
                    "acquired_at_utc": acquired_at,
                },
                owner_token,
            )
            metadata_paths.append(metadata_path)
        yield GpuLease(
            device_ids=normalized,
            job_id=selected_job,
            attempt=selected_attempt,
            owner_token=owner_token,
            metadata_paths=tuple(metadata_paths),
        )
    finally:
        for metadata_path in metadata_paths:
            _remove_owned_gpu_metadata(metadata_path, owner_token)
        for item in reversed(held):
            try:
                if item.file_acquired and item.fd is not None:
                    _unlock_file(item.fd)
            finally:
                try:
                    if item.fd is not None:
                        os.close(item.fd)
                finally:
                    if item.thread_acquired:
                        item.thread_lock.release()


@contextmanager
def model_load_lock(
    lock_root: Path,
    *,
    timeout_s: float | None = None,
    poll_s: float = 0.1,
    cancel_check: Callable[[], bool] | None = None,
    on_wait: Callable[[], None] | None = None,
) -> Iterator[Path]:
    """Acquire admission for one local model worker; waiting is cancelable.

    ``lock_root`` is supplied by the dispatcher, never inferred from a snapshot.
    The lock file is intentionally kept on
    disk; the OS releases the advisory lock when a worker exits, so a crashed
    process cannot leave a stale lock marker that blocks future work.
    """

    root = Path(lock_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".edmg-model-worker.lock"
    thread_lock = _thread_lock_for(lock_path)
    interval = float(poll_s)
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("Model worker poll interval must be finite and positive")
    deadline = _deadline(timeout_s)
    thread_acquired = False
    fd: int | None = None
    file_acquired = False
    notified = False

    def check_canceled() -> None:
        if cancel_check is not None and cancel_check():
            raise ModelLoadCanceled("Local model worker canceled before admission")

    def wait() -> None:
        nonlocal notified
        check_canceled()
        if not notified and on_wait is not None:
            notified = True
            on_wait()
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            raise ModelLoadTimeout("Timed out waiting for the internal model worker")
        time.sleep(interval if remaining is None else min(interval, remaining))

    try:
        while not thread_acquired:
            check_canceled()
            thread_acquired = thread_lock.acquire(blocking=False)
            if not thread_acquired:
                wait()

        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        # Windows permits locking beyond EOF. Do not write the sentinel byte:
        # another process may already own that byte between open and write.
        while not file_acquired:
            check_canceled()
            file_acquired = _try_file_lock(fd)
            if file_acquired:
                break
            wait()

        check_canceled()
        yield lock_path
    finally:
        try:
            if file_acquired and fd is not None:
                _unlock_file(fd)
        finally:
            try:
                if fd is not None:
                    os.close(fd)
            finally:
                if thread_acquired:
                    thread_lock.release()
