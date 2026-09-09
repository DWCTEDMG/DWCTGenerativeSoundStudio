from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any


MUSIC_GRAPH_SCHEMA_VERSION = "1.0"
MUSIC_GRAPH_ADAPTER_VERSION = "1"
MUSIC_GRAPH_CACHE_FILENAME = "music_graph_v1.json"
logger = logging.getLogger(__name__)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _weighted_tags_from_analysis(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Map CLAP or keyword tags into Music Graph semantics (P3-02)."""
    clap_raw = analysis.get("clap_tags") or analysis.get("semantic_tags") or analysis.get("semantics")
    tags: list[dict[str, Any]] = []
    if isinstance(clap_raw, list):
        for item in clap_raw:
            if isinstance(item, str) and item.strip():
                tags.append({"tag": item.strip(), "confidence": 0.72, "source": "clap"})
            elif isinstance(item, dict):
                label = str(item.get("tag") or item.get("label") or "").strip()
                if not label:
                    continue
                tags.append(
                    {
                        "tag": label,
                        "confidence": _as_float(item.get("confidence"), 0.65),
                        "source": str(item.get("source") or "clap"),
                    }
                )
    if tags:
        return tags[:24]
    for raw in list(analysis.get("tags") or [])[:16]:
        text = str(raw or "").strip()
        if text:
            tags.append({"tag": text, "confidence": 0.55, "source": "keyword"})
    return tags


def _lyrics_from_analysis(analysis: dict[str, Any]) -> dict[str, Any] | None:
    """Map ASR/transcript payloads into Music Graph lyrics (P3-02)."""
    raw = analysis.get("transcript") or analysis.get("lyrics")
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        return {"language": None, "words": [], "lines": [{"start": 0.0, "end": 0.0, "text": text}]}
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or "").strip()
    language = str(raw.get("language") or raw.get("lang") or "").strip() or None
    segments = raw.get("segments") if isinstance(raw.get("segments"), list) else []
    lines: list[dict[str, Any]] = []
    words: list[dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start = _as_float(segment.get("start") or segment.get("start_s"))
        end = _as_float(segment.get("end") or segment.get("end_s"), start)
        line_text = str(segment.get("text") or "").strip()
        if line_text:
            lines.append({"start": start, "end": max(start, end), "text": line_text})
        for word in segment.get("words") or []:
            if not isinstance(word, dict):
                continue
            token = str(word.get("word") or word.get("text") or "").strip()
            if not token:
                continue
            words.append(
                {
                    "t": _as_float(word.get("start") or word.get("t"), start),
                    "text": token,
                    "confidence": _as_float(word.get("confidence"), 0.7),
                }
            )
    if not lines and text:
        lines = [{"start": 0.0, "end": 0.0, "text": text}]
    if not text and not lines:
        if raw.get("error"):
            return {"language": language, "words": [], "lines": [], "error": str(raw.get("error"))}
        return None
    payload: dict[str, Any] = {"language": language, "words": words, "lines": lines}
    if raw.get("source"):
        payload["source"] = str(raw.get("source"))
    if raw.get("note"):
        payload["note"] = str(raw.get("note"))
    return payload


def _stems_from_analysis(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    stems: list[dict[str, Any]] = []
    raw_stems = analysis.get("stems")
    if isinstance(raw_stems, dict):
        for kind, details in raw_stems.items():
            entry: dict[str, Any] = {"kind": str(kind), "features": {}}
            if isinstance(details, dict):
                if details.get("asset") or details.get("path"):
                    entry["asset"] = str(details.get("asset") or details.get("path"))
                entry["features"] = {
                    key: details[key]
                    for key in ("energy", "weight", "role", "available")
                    if key in details
                }
            stems.append(entry)
    elif isinstance(raw_stems, list):
        for item in raw_stems:
            if isinstance(item, dict) and item.get("kind"):
                stems.append(dict(item))

    multitrack = (analysis.get("features") or {}).get("multitrack") if isinstance(analysis.get("features"), dict) else None
    if isinstance(multitrack, dict):
        for track in list(multitrack.get("tracks") or []):
            if not isinstance(track, dict):
                continue
            name = str(track.get("name") or track.get("role") or "track").strip()
            if any(str(existing.get("kind") or "") == name for existing in stems):
                continue
            stems.append(
                {
                    "kind": name,
                    "features": {
                        "weight": _as_float(track.get("weight"), 1.0),
                        "role": str(track.get("role") or name),
                        "available": bool(track.get("available", True)),
                    },
                }
            )
    if not stems:
        stems = [{"kind": "mixed", "features": {"role": "full_mix", "weight": 1.0, "available": True}}]
    return stems


def _analysis_runs(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    runs = analysis.get("analysisRuns") if isinstance(analysis.get("analysisRuns"), list) else []
    if runs:
        return [dict(item) for item in runs if isinstance(item, dict)]
    timestamp = analysis.get("timestamp") or analysis.get("analyzed_at")
    if timestamp:
        return [
            {
                "run_id": "legacy",
                "completed_at": timestamp,
                "sources": ["legacy_analysis_meta"],
            }
        ]
    return [{"run_id": "compat", "completed_at": None, "sources": ["compatibility_adapter"]}]


def music_graph_source_fingerprint(
    analysis: dict[str, Any] | None,
    *,
    audio_filename: str | None = None,
    duration_s: float | None = None,
) -> str:
    payload = {
        "adapter_version": MUSIC_GRAPH_ADAPTER_VERSION,
        "schema_version": MUSIC_GRAPH_SCHEMA_VERSION,
        "analysis": analysis or {},
        "audio_filename": audio_filename,
        "duration_s": duration_s,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def music_graph_from_analysis(
    analysis: dict[str, Any] | None,
    *,
    audio_filename: str | None = None,
    duration_s: float | None = None,
) -> dict[str, Any]:
    """Compatibility adapter: map existing analysis meta into Music Graph v1 shape."""
    analysis = dict(analysis or {})
    source_fingerprint = music_graph_source_fingerprint(
        analysis,
        audio_filename=audio_filename,
        duration_s=duration_s,
    )
    features = dict(analysis.get("features") or {})
    beats_raw = analysis.get("beats") or features.get("beats") or features.get("beat_times") or []
    sections_raw = analysis.get("sections") or features.get("sections") or []
    bpm = _as_float(features.get("bpm") or analysis.get("bpm"))
    duration = _as_float(
        duration_s or features.get("duration_s") or analysis.get("duration_s") or features.get("duration")
    )

    beats: list[dict[str, Any]] = []
    for item in beats_raw:
        if isinstance(item, (int, float)):
            beats.append({"t": float(item), "confidence": 1.0})
        elif isinstance(item, dict) and "t" in item:
            beats.append({"t": float(item.get("t") or 0.0), "confidence": _as_float(item.get("confidence"), 1.0)})

    sections: list[dict[str, Any]] = []
    for item in sections_raw:
        if not isinstance(item, dict):
            continue
        sections.append(
            {
                "start": _as_float(item.get("start") or item.get("start_s") or item.get("startTime")),
                "end": _as_float(item.get("end") or item.get("end_s") or item.get("endTime")),
                "label": str(item.get("label") or item.get("name") or "section"),
                "confidence": _as_float(item.get("confidence"), 1.0),
                "energy": _as_float(item.get("energy") or item.get("avgEnergy") or item.get("avg_energy"), 0.0) or None,
            }
        )
        if sections[-1]["energy"] is None:
            sections[-1].pop("energy", None)

    semantics_tags = _weighted_tags_from_analysis(analysis)
    lyrics = _lyrics_from_analysis(analysis)
    stems = _stems_from_analysis(analysis)

    feature_curves = {
        key: features.get(key)
        for key in ("energy", "energy_curve", "loudness", "spectral_flux", "brightness", "harmonicity")
        if features.get(key) is not None
    }

    confidence_notes = [
        "Compatibility adapter from legacy analysis meta; bars may be empty until re-analysis.",
    ]
    if not semantics_tags:
        confidence_notes.append("Semantic tags unavailable; CLAP lane optional and offline-safe.")
    if lyrics and lyrics.get("error"):
        confidence_notes.append("ASR transcript failed; lyrics block records the error for inspection.")

    graph: dict[str, Any] = {
        "schemaVersion": MUSIC_GRAPH_SCHEMA_VERSION,
        "graphRevision": source_fingerprint,
        "provenance": {
            "adapterVersion": MUSIC_GRAPH_ADAPTER_VERSION,
            "sourceFingerprint": source_fingerprint,
            "storage": "derived_in_memory",
        },
        "source": {"filename": audio_filename, "kind": "project_audio"},
        "timebase": {"sampleRate": int(features.get("sample_rate") or 44100), "durationSeconds": duration},
        "tempo": {"bpm": bpm, "confidence": _as_float(features.get("bpm_confidence"), 0.5 if bpm else 0.0)},
        "meter": {
            "numerator": int(features.get("meter_numerator") or 4),
            "denominator": int(features.get("meter_denominator") or 4),
            "confidence": _as_float(features.get("meter_confidence"), 0.5),
        },
        "beats": beats,
        "bars": [],
        "sections": sections,
        "energy": analysis.get("energy") or features.get("energy") or features.get("energy_curve") or [],
        "stems": stems,
        "features": feature_curves,
        "analysisRuns": _analysis_runs(analysis),
        "confidenceNotes": confidence_notes,
    }
    if lyrics is not None:
        graph["lyrics"] = lyrics
    if semantics_tags:
        graph["semantics"] = {"tags": semantics_tags}
    return graph


def music_graph_for_project(project_dir: Path, meta: dict[str, Any] | None) -> dict[str, Any]:
    """Return the deterministic project Music Graph, materializing its derived cache when needed."""
    project_meta = meta if isinstance(meta, dict) else {}
    audio = project_meta.get("audio") if isinstance(project_meta.get("audio"), dict) else {}
    analysis = project_meta.get("analysis") if isinstance(project_meta.get("analysis"), dict) else {}
    audio_filename = str(audio.get("filename") or "") or None
    duration_s = _as_float(audio.get("duration_s") or analysis.get("duration_s")) or None
    fingerprint = music_graph_source_fingerprint(
        analysis,
        audio_filename=audio_filename,
        duration_s=duration_s,
    )
    cache_path = Path(project_dir) / "analysis" / MUSIC_GRAPH_CACHE_FILENAME
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError, OSError):
        cached = None
    if isinstance(cached, dict) and cached.get("graphRevision") == fingerprint:
        return cached

    graph = music_graph_from_analysis(
        analysis,
        audio_filename=audio_filename,
        duration_s=duration_s,
    )
    temporary = cache_path.with_name(f".{cache_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        graph["provenance"]["storage"] = "persistent_project_cache"
        temporary.write_text(
            json.dumps(graph, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
            encoding="utf-8",
        )
        os.replace(temporary, cache_path)
    except OSError as exc:
        graph["provenance"]["storage"] = "derived_in_memory"
        logger.warning("Could not persist Music Graph cache at %s: %s", cache_path, exc)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Could not remove temporary Music Graph cache at %s: %s", temporary, exc)
    return graph


def section_energy_at_time(graph: dict[str, Any] | None, midpoint_s: float, *, default: float = 0.5) -> float:
    """Resolve section energy from a Music Graph at a timeline midpoint."""
    sections = list((graph or {}).get("sections") or [])
    for section in sections:
        if not isinstance(section, dict):
            continue
        start = _as_float(section.get("start"))
        end = _as_float(section.get("end"), start)
        if start <= midpoint_s <= max(start, end):
            if section.get("energy") is not None:
                return max(0.0, min(1.0, _as_float(section.get("energy"), default)))
            return default
    return default
