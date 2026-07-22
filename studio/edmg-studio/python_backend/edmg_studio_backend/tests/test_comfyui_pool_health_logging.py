from __future__ import annotations

import logging

from edmg_studio_backend.integrations import comfyui_pool


def test_offline_comfyui_health_logs_only_on_state_transition(monkeypatch, caplog) -> None:
    pool = comfyui_pool.ComfyUINodePool(
        [{"url": "http://127.0.0.1:8188"}],
        health_check_interval_s=0,
    )
    node = next(iter(pool._nodes.values()))

    def unavailable(*_args, **_kwargs):
        raise ConnectionError("offline")

    monkeypatch.setattr(comfyui_pool.comfy, "get_object_info", unavailable)
    caplog.set_level(logging.ERROR, logger=comfyui_pool.__name__)

    pool._check_health_if_needed(node)
    pool._check_health_if_needed(node)

    failures = [record for record in caplog.records if "health check failed" in record.message]
    assert len(failures) == 1
    assert node.healthy is False
    assert node.last_error == "ComfyUI health check failed"

    monkeypatch.setattr(comfyui_pool.comfy, "get_object_info", lambda *_args, **_kwargs: {})
    pool._check_health_if_needed(node)
    assert node.healthy is True

    monkeypatch.setattr(comfyui_pool.comfy, "get_object_info", unavailable)
    pool._check_health_if_needed(node)

    failures = [record for record in caplog.records if "health check failed" in record.message]
    assert len(failures) == 2
