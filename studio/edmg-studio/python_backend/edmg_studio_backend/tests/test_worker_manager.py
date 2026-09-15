from __future__ import annotations

import threading
from contextlib import contextmanager
from types import SimpleNamespace

from edmg_studio_backend.services.worker_manager import WorkerManager


def test_worker_manager_maintains_claimed_lease_during_execution() -> None:
    stopped = threading.Event()
    lease_active = False
    executed = False

    class Jobs:
        def claim_next_queued(self):
            return SimpleNamespace(id="job", project_id="project", attempt=1)

        @contextmanager
        def maintain_lease(self, _job):
            nonlocal lease_active
            lease_active = True
            try:
                yield
            finally:
                lease_active = False

    def run_job(_job) -> None:
        nonlocal executed
        assert lease_active
        executed = True
        stopped.set()

    manager = WorkerManager(Jobs(), run_job, poll_interval_s=0.01)
    manager._stop = stopped

    manager._loop()

    assert executed
    assert not lease_active
