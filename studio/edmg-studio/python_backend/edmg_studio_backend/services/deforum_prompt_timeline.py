from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

PromptMapInput = Mapping[int | str, Any] | Iterable[tuple[int | str, Any]] | None


def normalize_prompt_map(prompts: PromptMapInput) -> list[tuple[int, str]]:
    """Normalize prompt maps keyed by frame index."""
    if prompts is None:
        return []

    raw_pairs: list[tuple[Any, Any]]
    if isinstance(prompts, Mapping):
        raw_pairs = list(prompts.items())
    else:
        raw_pairs = []
        for item in prompts:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            raw_pairs.append((item[0], item[1]))

    dedup: dict[int, str] = {}
    for raw_frame, raw_prompt in raw_pairs:
        try:
            frame = max(0, int(raw_frame))
        except Exception:
            continue
        dedup[frame] = str(raw_prompt or "")
    return sorted(dedup.items(), key=lambda item: item[0])


def resolve_prompt_frame(prompts: PromptMapInput, frame_idx: int, default: str = "") -> str:
    """Resolve the active prompt at a frame using latest-keyframe-wins semantics."""
    pairs = normalize_prompt_map(prompts)
    if not pairs:
        return default

    frame = int(frame_idx)
    if frame <= pairs[0][0]:
        return pairs[0][1]

    active = default
    for prompt_frame, prompt in pairs:
        if frame < prompt_frame:
            break
        active = prompt
    return active
