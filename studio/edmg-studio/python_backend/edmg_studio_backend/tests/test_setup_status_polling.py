from __future__ import annotations

from edmg_studio_backend import app as backend_app
from edmg_studio_backend.services import setup_wizard


def test_setup_status_caches_expensive_diagnostics_and_refresh_bypasses_cache(monkeypatch):
    calls = 0

    def compute(*, include_optional: bool = False):
        nonlocal calls
        calls += 1
        return {"ok": True, "include_optional": include_optional}

    monkeypatch.setattr(backend_app, "_compute_setup_status", compute)
    backend_app._clear_setup_status_cache()

    first = backend_app.setup_status()
    second = backend_app.setup_status()
    refreshed = backend_app.setup_status(refresh=True)

    assert calls == 2
    assert first["status_cache"]["cached"] is False
    assert second["status_cache"]["cached"] is True
    assert refreshed["status_cache"]["cached"] is False
    assert isinstance(second["tasks"], list)


def test_setup_task_list_never_runs_full_status_probes(monkeypatch):
    monkeypatch.setattr(
        backend_app,
        "_compute_setup_status",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("full probe should not run")),
    )

    result = backend_app.setup_task_list()

    assert result["ok"] is True
    assert isinstance(result["tasks"], list)


def test_ollama_probe_does_not_expose_request_exception(monkeypatch):
    def fail_probe(*_args, **_kwargs):
        raise RuntimeError("secret request diagnostics")

    monkeypatch.setattr(setup_wizard.requests, "get", fail_probe)

    result = setup_wizard.check_ollama("http://127.0.0.1:11434", "demo")

    assert result["ok"] is False
    assert result["error"] == "Ollama status probe failed"
    assert "secret request diagnostics" not in result["error"]


def test_non_ollama_planner_skips_ollama_network_probe(monkeypatch):
    check_ollama_calls = 0

    def check_ollama(*_args, **_kwargs):
        nonlocal check_ollama_calls
        check_ollama_calls += 1
        return {"ok": True, "model_present": True}

    monkeypatch.setattr(
        backend_app,
        "_setup_ai_config",
        lambda: {
            "provider": "rule_based",
            "label": "Rule-based fallback",
            "ollama_required": False,
            "model_required": False,
        },
    )
    monkeypatch.setattr(backend_app, "check_ollama", check_ollama)
    monkeypatch.setattr(backend_app, "_find_ollama_exe", lambda *_args: None)
    monkeypatch.setattr(backend_app, "_resolve_comfy_checkpoint_name", lambda *_args, **_kwargs: ("demo.safetensors", None))
    monkeypatch.setattr(backend_app.comfy_pool, "diagnose", lambda *_args, **_kwargs: {"compatible": False})
    monkeypatch.setattr(backend_app, "comfy_portable_installed", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        backend_app,
        "_system_readiness_report",
        lambda: {"checks": {"ffmpeg": {"ok": True, "path": "ffmpeg"}}},
    )
    monkeypatch.setattr(backend_app, "check_backend_bundle", lambda: {"ok": True})
    monkeypatch.setattr(backend_app, "core_status", lambda: {"available": True})
    monkeypatch.setattr(backend_app, "_find_7z_exe", lambda *_args, **_kwargs: "7z")
    monkeypatch.setattr(backend_app, "_hardware_profile", lambda: {})

    result = backend_app._compute_setup_status()

    assert check_ollama_calls == 0
    assert result["ollama"]["skipped"] is True
    assert result["ollama"]["optional"] is True
