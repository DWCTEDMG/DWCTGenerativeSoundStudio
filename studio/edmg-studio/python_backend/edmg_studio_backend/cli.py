from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from .cuda_dll_path import prepare_cuda_dll_path

prepare_cuda_dll_path()

import uvicorn

from .config import Settings
from .security import validate_remote_bind_security


def _configure_backend_logging(logs_dir: Path) -> Path:
    log_path = logs_dir / "backend" / "backend-errors.log"
    package_logger = logging.getLogger("edmg_studio_backend")
    resolved_path = log_path.resolve()
    for handler in package_logger.handlers:
        if isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) == resolved_path:
            return resolved_path

    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        resolved_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
        delay=True,
    )
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s [pid=%(process)d] %(message)s"
    ))
    package_logger.setLevel(logging.WARNING)
    package_logger.addHandler(handler)
    return resolved_path


def _run_single_job(project_id: str, job_id: str, *, attempt: int | None = None) -> int:
    """Execute one already-claimed job in this process and finalize it.

    Used by the worker for process isolation: heavy render jobs run here so they
    cannot starve the FastAPI server. Progress/logs/results are written to the
    shared job store that the server polls.
    """
    from .app import _execute_job, jobs

    job = jobs.get(project_id, job_id)
    if job is None:
        sys.stderr.write(f"Job not found: project={project_id} job={job_id}\n")
        return 2
    if job.status not in ("queued", "running"):
        return 0 if job.status in ("succeeded", "canceled") else 1
    if attempt is not None and job.attempt != attempt:
        sys.stderr.write("Job attempt changed before the worker started.\n")
        return 2
    _execute_job(job)
    latest = jobs.get(project_id, job_id) or job
    return 0 if latest.status in ("succeeded", "canceled") else 1


def main() -> None:
    p = argparse.ArgumentParser(
        prog="edmg-studio-backend",
        description="EDMG Studio backend server.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="Run FastAPI server.")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=7863)
    s.add_argument("--reload", action="store_true")

    rj = sub.add_parser(
        "run-job",
        help="Execute a single claimed job in this process (used by the worker for isolation).",
    )
    rj.add_argument("--project", required=True)
    rj.add_argument("--job", required=True)
    rj.add_argument("--attempt", type=int)

    runtime_worker = sub.add_parser("runtime-worker", help="Isolated optional acceleration worker")
    runtime_worker.add_argument("--directory", required=True)

    args = p.parse_args()
    log_path = _configure_backend_logging(Settings().logs_dir)
    logging.getLogger(__name__).info("Backend warning/error log: %s", log_path)

    if args.cmd == "runtime-worker":
        from .runtime.worker import serve
        serve(Path(args.directory))
    elif args.cmd == "serve":
        try:
            validate_remote_bind_security(args.host)
        except RuntimeError as exc:
            p.error(str(exc))
        from .app import app

        uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
    elif args.cmd == "run-job":
        raise SystemExit(_run_single_job(args.project, args.job, attempt=args.attempt))


if __name__ == "__main__":
    main()
