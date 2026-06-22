from __future__ import annotations

import argparse
import sys

import uvicorn

from .app import app, jobs, _execute_job


def _run_single_job(project_id: str, job_id: str) -> int:
    """Execute one already-claimed job in this process and finalize it.

    Used by the worker for process isolation: heavy render jobs run here so they
    cannot starve the FastAPI server. Progress/logs/results are written to the
    file-based job store that the server polls.
    """
    job = jobs.get(project_id, job_id)
    if job is None:
        sys.stderr.write(f"Job not found: project={project_id} job={job_id}\n")
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

    args = p.parse_args()

    if args.cmd == "serve":
        uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
    elif args.cmd == "run-job":
        raise SystemExit(_run_single_job(args.project, args.job))


if __name__ == "__main__":
    main()