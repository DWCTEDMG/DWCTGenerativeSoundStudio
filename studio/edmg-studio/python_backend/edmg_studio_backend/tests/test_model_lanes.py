from __future__ import annotations

from edmg_studio_backend.domain.model_lanes import (
    annotate_entry,
    can_promote,
    infer_lane,
    promotion_blockers,
)


def test_infer_lane_from_recommended_default() -> None:
    assert infer_lane({"recommended": "default"}) == "recommended"
    assert infer_lane({"tags": ["legacy"]}) == "legacy"
    assert infer_lane({"installable": False}) == "research"


def test_promotion_gates_and_stable_blockers() -> None:
    assert can_promote("experimental", "recommended")
    assert not can_promote("research", "stable")
    blockers = promotion_blockers(
        {"id": "m1", "recommended": "default", "license_id": "MIT"},
        target_lane="stable",
        has_benchmark=False,
        license_accepted=True,
    )
    assert "missing_benchmark_json" in blockers


def test_annotate_entry_includes_lane_gates() -> None:
    annotated = annotate_entry({"id": "m1", "recommended": "advanced"})
    assert annotated["lane"] == "experimental"
    assert "recommended" in annotated["lane_gates"]["promotable_to"]
