from __future__ import annotations

from scripts.studio_genuine_workflow_smoke import run_genuine_workflow_smoke


def test_studio_genuine_workflow_smoke():
    result = run_genuine_workflow_smoke()

    assert result["ok"] is True
    assert result["variant_count"] == 1
    assert result["scene_count"] >= 1
    assert result["timeline_track_count"] >= 1
    assert result["render_error"]["code"] == "NO_RENDER_ROUTE"
    assert result["render_error"]["status_code"] == 400
    assert result["persisted"] == {"has_plan": True, "has_timeline": True}
