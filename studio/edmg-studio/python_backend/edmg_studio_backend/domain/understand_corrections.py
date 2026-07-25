from __future__ import annotations

import time
from typing import Any


DERIVED_META_KEYS = (
    "last_conductor_plan",
    "last_conductor_intent",
)


def _normalize_beats(beats: list[Any]) -> list[Any]:
    normalized: list[Any] = []
    for item in beats:
        if isinstance(item, (int, float)):
            normalized.append(float(item))
        elif isinstance(item, dict):
            normalized.append(dict(item))
    return normalized


def _normalize_sections(sections: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in sections:
        if not isinstance(item, dict):
            continue
        row = {
            "start": float(item.get("start") or item.get("start_s") or 0.0),
            "end": float(item.get("end") or item.get("end_s") or 0.0),
            "label": str(item.get("label") or item.get("name") or "section"),
        }
        if item.get("confidence") is not None:
            row["confidence"] = float(item.get("confidence"))
        if item.get("energy") is not None:
            row["energy"] = float(item.get("energy"))
        rows.append(row)
    return rows


def _normalize_semantic_tags(tags: list[Any]) -> list[Any]:
    normalized: list[Any] = []
    for item in tags:
        if isinstance(item, str) and item.strip():
            normalized.append(item.strip())
        elif isinstance(item, dict):
            label = str(item.get("tag") or item.get("label") or "").strip()
            if not label:
                continue
            entry: dict[str, Any] = {"tag": label}
            if item.get("confidence") is not None:
                entry["confidence"] = float(item.get("confidence"))
            if item.get("source"):
                entry["source"] = str(item.get("source"))
            normalized.append(entry)
    return normalized


def apply_understand_corrections(
    meta: dict[str, Any],
    *,
    sections: list[dict[str, Any]] | None = None,
    beats: list[Any] | None = None,
    lyrics_lines: list[dict[str, Any]] | None = None,
    semantic_tags: list[Any] | None = None,
    tempo_bpm: float | None = None,
    reason: str = "manual_edit",
) -> dict[str, Any]:
    """Apply manual Understand corrections to project analysis meta and invalidate derived plans."""
    analysis = dict(meta.get("analysis") or {})
    features = dict(analysis.get("features") or {})
    changed: list[str] = []

    if sections is not None:
        analysis["sections"] = _normalize_sections(sections)
        changed.append("sections")
    if beats is not None:
        analysis["beats"] = _normalize_beats(beats)
        changed.append("beats")
    if lyrics_lines is not None:
        transcript = dict(analysis.get("transcript") or {})
        lines = []
        for line in lyrics_lines:
            if not isinstance(line, dict):
                continue
            text = str(line.get("text") or "").strip()
            if not text:
                continue
            lines.append(
                {
                    "start": float(line.get("start") or 0.0),
                    "end": float(line.get("end") or line.get("start") or 0.0),
                    "text": text,
                }
            )
        transcript["segments"] = lines
        transcript["text"] = " ".join(item["text"] for item in lines)
        analysis["transcript"] = transcript
        changed.append("lyrics")
    if semantic_tags is not None:
        normalized = _normalize_semantic_tags(semantic_tags)
        analysis["semantic_tags"] = normalized
        analysis["tags"] = [
            str(item.get("tag") if isinstance(item, dict) else item)
            for item in normalized
            if (isinstance(item, dict) and item.get("tag")) or isinstance(item, str)
        ]
        changed.append("semantics")
    if tempo_bpm is not None:
        features["bpm"] = float(tempo_bpm)
        analysis["bpm"] = float(tempo_bpm)
        changed.append("tempo")

    invalidated: list[str] = []
    if changed:
        if features:
            analysis["features"] = features
        runs = list(analysis.get("analysisRuns") or [])
        runs.append(
            {
                "run_id": f"manual-{int(time.time())}",
                "completed_at": time.time(),
                "sources": ["understand_corrections"],
                "reason": reason,
                "changed": list(changed),
            }
        )
        analysis["analysisRuns"] = runs
        analysis["corrected_at"] = time.time()
        meta["analysis"] = analysis
        for key in DERIVED_META_KEYS:
            if key in meta:
                meta.pop(key, None)
                invalidated.append(key)

    return {"changed": changed, "invalidated": invalidated}
