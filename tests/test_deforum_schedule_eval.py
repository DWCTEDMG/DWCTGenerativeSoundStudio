from __future__ import annotations

from edmg_studio_backend.services.deforum_schedule import coerce_schedule_pairs, evaluate_schedule


def test_schedule_exact_keyframe_lookup_and_last_wins():
    pairs = coerce_schedule_pairs("0:(1.0), 12:(1.05), 12:(1.10), 24:(0.98)")
    assert pairs == [(0, 1.0), (12, 1.1), (24, 0.98)]
    assert evaluate_schedule(pairs, 12) == 1.1


def test_schedule_interpolates_between_keyframes():
    value = evaluate_schedule("0:(1.0), 24:(1.24)", 12)
    assert value == 1.12


def test_schedule_returns_default_when_missing():
    assert evaluate_schedule("", 5, default=0.35) == 0.35
