from __future__ import annotations

from edmg_studio_backend.domain.motion_grammar import apply_motion_phrases_to_timeline, compile_motion_phrase


def test_compile_and_apply_motion_phrases() -> None:
    clip = compile_motion_phrase("accent", start_s=1.0, end_s=2.5)
    assert clip["data"]["motion_grammar"] == "accent"
    timeline = apply_motion_phrases_to_timeline(
        {"tracks": []},
        [{"phrase": "prepare", "start_s": 0.0, "end_s": 1.0}, {"phrase": "settle", "start_s": 4.0, "end_s": 5.0}],
        overwrite_motion_track=True,
    )
    motion = next(t for t in timeline["tracks"] if t["type"] == "motion")
    assert len(motion["clips"]) == 2
    assert motion["clips"][0]["data"]["motion_grammar"] == "prepare"
