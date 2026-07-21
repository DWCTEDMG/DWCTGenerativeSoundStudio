from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class TimelineCommand:
    name: str
    undo: Callable[[], None]
    redo: Callable[[], None]
    label: str = ""


class TimelineCommandStack:
    def __init__(self, *, limit: int = 100):
        self._undo: list[TimelineCommand] = []
        self._redo: list[TimelineCommand] = []
        self._limit = max(1, int(limit))

    def push(self, command: TimelineCommand) -> None:
        self._undo.append(command)
        if len(self._undo) > self._limit:
            self._undo = self._undo[-self._limit :]
        self._redo.clear()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> TimelineCommand | None:
        if not self._undo:
            return None
        cmd = self._undo.pop()
        cmd.undo()
        self._redo.append(cmd)
        return cmd

    def redo(self) -> TimelineCommand | None:
        if not self._redo:
            return None
        cmd = self._redo.pop()
        cmd.redo()
        self._undo.append(cmd)
        return cmd

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()


def replace_timeline_value(
    *,
    get_value: Callable[[], Any],
    set_value: Callable[[Any], None],
    next_value: Any,
    name: str,
    stack: TimelineCommandStack,
    label: str = "",
) -> None:
    """Apply a value change and record undo/redo snapshots."""
    previous = get_value()
    set_value(next_value)

    def undo() -> None:
        set_value(previous)

    def redo() -> None:
        set_value(next_value)

    stack.push(TimelineCommand(name=name, undo=undo, redo=redo, label=label or name))
