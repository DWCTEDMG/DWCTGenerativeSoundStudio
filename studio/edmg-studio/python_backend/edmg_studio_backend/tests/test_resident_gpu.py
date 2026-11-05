from __future__ import annotations

from types import SimpleNamespace

from edmg_studio_backend.services.resident_gpu import resident_gpu_lease


def test_lease_is_a_noop_without_a_host_coordinator(monkeypatch):
    monkeypatch.delenv("EDMG_GPU_COORDINATOR_SOCKET", raising=False)
    job = SimpleNamespace(type="internal_video", payload={})
    with resident_gpu_lease(job):
        assert True


def test_lease_skips_jobs_that_do_not_use_local_models(monkeypatch):
    monkeypatch.setenv("EDMG_GPU_COORDINATOR_SOCKET", "/not-used.sock")
    job = SimpleNamespace(type="assemble_variant", payload={})
    with resident_gpu_lease(job):
        assert True
