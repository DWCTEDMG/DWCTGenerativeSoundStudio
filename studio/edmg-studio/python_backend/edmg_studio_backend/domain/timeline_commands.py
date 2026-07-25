from __future__ import annotations

from copy import deepcopy
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


def clone_timeline(timeline: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(timeline or {})


def move_clip_in_timeline(
    timeline: dict[str, Any],
    *,
    track_idx: int,
    clip_idx: int,
    start_s: float,
    end_s: float,
) -> dict[str, Any]:
    """Move or resize a clip by assigning new start/end seconds."""
    next_timeline = clone_timeline(timeline)
    tracks = list(next_timeline.get("tracks") or [])
    if track_idx < 0 or track_idx >= len(tracks):
        return next_timeline
    track = dict(tracks[track_idx])
    clips = list(track.get("clips") or [])
    if clip_idx < 0 or clip_idx >= len(clips):
        return next_timeline
    clip = dict(clips[clip_idx])
    clip["start_s"] = float(start_s)
    clip["end_s"] = float(end_s)
    clips[clip_idx] = clip
    track["clips"] = clips
    tracks[track_idx] = track
    next_timeline["tracks"] = tracks
    return next_timeline


def trim_clip_in_timeline(
    timeline: dict[str, Any],
    *,
    track_idx: int,
    clip_idx: int,
    start_s: float | None = None,
    end_s: float | None = None,
) -> dict[str, Any]:
    """Trim a clip from the left, right, or both edges."""
    next_timeline = clone_timeline(timeline)
    tracks = list(next_timeline.get("tracks") or [])
    if track_idx < 0 or track_idx >= len(tracks):
        return next_timeline
    track = dict(tracks[track_idx])
    clips = list(track.get("clips") or [])
    if clip_idx < 0 or clip_idx >= len(clips):
        return next_timeline
    clip = dict(clips[clip_idx])
    if start_s is not None:
        clip["start_s"] = float(start_s)
    if end_s is not None:
        clip["end_s"] = float(end_s)
    clips[clip_idx] = clip
    track["clips"] = clips
    tracks[track_idx] = track
    next_timeline["tracks"] = tracks
    return next_timeline


def apply_timeline_mutation(
    *,
    get_timeline: Callable[[], dict[str, Any]],
    set_timeline: Callable[[dict[str, Any]], None],
    mutate: Callable[[dict[str, Any]], dict[str, Any]],
    stack: TimelineCommandStack,
    name: str,
    label: str = "",
) -> dict[str, Any]:
    """Apply a timeline mutation and record undo/redo snapshots."""
    previous = clone_timeline(get_timeline())
    next_value = mutate(clone_timeline(previous))
    set_timeline(next_value)

    def undo() -> None:
        set_timeline(clone_timeline(previous))

    def redo() -> None:
        set_timeline(clone_timeline(next_value))

    stack.push(TimelineCommand(name=name, undo=undo, redo=redo, label=label or name))
    return next_value
