import { renderHook, act } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useTimelineHistory } from "../shared/commands/useTimelineHistory";

describe("useTimelineHistory", () => {
  it("records move and trim edits as undoable snapshots", () => {
    const before = {
      tracks: [{ clips: [{ id: "clip-1", start_s: 0, end_s: 2 }] }],
    };
    const moved = {
      tracks: [{ clips: [{ id: "clip-1", start_s: 1, end_s: 3 }] }],
    };
    const trimmed = {
      tracks: [{ clips: [{ id: "clip-1", start_s: 1, end_s: 2.5 }] }],
    };

    const { result } = renderHook(() => useTimelineHistory());

    act(() => {
      result.current.push(before, moved, "move_clip");
    });
    expect(result.current.canUndo).toBe(true);

    let restored: Record<string, unknown> | null = null;
    act(() => {
      restored = result.current.undo();
    });
    expect(restored).toEqual(before);

    let redone: Record<string, unknown> | null = null;
    act(() => {
      redone = result.current.redo();
    });
    expect(redone).toEqual(moved);

    act(() => {
      result.current.push(moved, trimmed, "trim_clip");
    });
    act(() => {
      restored = result.current.undo();
    });
    expect(restored).toEqual(moved);
  });
});
