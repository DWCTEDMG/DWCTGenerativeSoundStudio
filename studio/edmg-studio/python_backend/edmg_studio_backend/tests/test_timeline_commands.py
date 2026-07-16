from __future__ import annotations

from edmg_studio_backend.domain.timeline_commands import TimelineCommandStack, replace_timeline_value


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
