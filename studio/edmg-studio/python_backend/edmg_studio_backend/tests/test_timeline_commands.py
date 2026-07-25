from __future__ import annotations

from edmg_studio_backend.domain.timeline_commands import (
    TimelineCommandStack,
    apply_timeline_mutation,
    move_clip_in_timeline,
    replace_timeline_value,
    trim_clip_in_timeline,
)


def test_timeline_command_stack_undo_redo() -> None:
    state = {"layers": [{"id": "a"}]}
    stack = TimelineCommandStack()

    def get_value():
        return list(state["layers"])

    def set_value(value):
        state["layers"] = list(value)

    replace_timeline_value(
        get_value=get_value,
        set_value=set_value,
        next_value=[{"id": "a"}, {"id": "b"}],
        name="add_layer",
        stack=stack,
    )
    assert len(state["layers"]) == 2
    assert stack.can_undo()
    stack.undo()
    assert state["layers"] == [{"id": "a"}]
    stack.redo()
    assert [layer["id"] for layer in state["layers"]] == ["a", "b"]


def test_move_and_trim_clip_commands_support_undo_redo() -> None:
    timeline = {
        "tracks": [
            {
                "id": "motion",
                "clips": [{"id": "clip-1", "start_s": 0.0, "end_s": 2.0}],
            }
        ]
    }
    stack = TimelineCommandStack()

    def get_timeline():
        return timeline

    def set_timeline(value):
        timeline.clear()
        timeline.update(value)

    apply_timeline_mutation(
        get_timeline=get_timeline,
        set_timeline=set_timeline,
        mutate=lambda current: move_clip_in_timeline(
            current,
            track_idx=0,
            clip_idx=0,
            start_s=1.0,
            end_s=3.0,
        ),
        stack=stack,
        name="move_clip",
        label="move_clip",
    )
    assert timeline["tracks"][0]["clips"][0]["start_s"] == 1.0
    stack.undo()
    assert timeline["tracks"][0]["clips"][0]["start_s"] == 0.0

    apply_timeline_mutation(
        get_timeline=get_timeline,
        set_timeline=set_timeline,
        mutate=lambda current: trim_clip_in_timeline(
            current,
            track_idx=0,
            clip_idx=0,
            end_s=1.5,
        ),
        stack=stack,
        name="trim_clip",
        label="trim_clip",
    )
    assert timeline["tracks"][0]["clips"][0]["end_s"] == 1.5
    stack.undo()
    assert timeline["tracks"][0]["clips"][0]["end_s"] == 2.0
