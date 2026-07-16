import { useRef, useState } from "react";

type TimelineSnapshot = Record<string, unknown>;

type HistoryEntry = {
  before: TimelineSnapshot;
  after: TimelineSnapshot;
  label: string;
};

function cloneTimeline(value: TimelineSnapshot): TimelineSnapshot {
  return JSON.parse(JSON.stringify(value || {})) as TimelineSnapshot;
}

export function useTimelineHistory(limit = 100) {
  const undoRef = useRef<HistoryEntry[]>([]);
  const redoRef = useRef<HistoryEntry[]>([]);
  const [version, setVersion] = useState(0);

  const bump = () => setVersion((v) => v + 1);

  const push = (before: TimelineSnapshot, after: TimelineSnapshot, label = "edit") => {
    undoRef.current = [
      ...undoRef.current.slice(-(Math.max(1, limit) - 1)),
      { before: cloneTimeline(before), after: cloneTimeline(after), label },
    ];
    redoRef.current = [];
    bump();
  };

  const canUndo = undoRef.current.length > 0;
  const canRedo = redoRef.current.length > 0;

  const undo = (): TimelineSnapshot | null => {
    const entry = undoRef.current.pop();
    if (!entry) return null;
    redoRef.current.push(entry);
    bump();
    return cloneTimeline(entry.before);
  };

  const redo = (): TimelineSnapshot | null => {
    const entry = redoRef.current.pop();
    if (!entry) return null;
    undoRef.current.push(entry);
    bump();
    return cloneTimeline(entry.after);
  };

  const clear = () => {
    undoRef.current = [];
    redoRef.current = [];
    bump();
  };

  return {
    version,
    push,
    undo,
    redo,
    clear,
    canUndo,
    canRedo,
  };
}
