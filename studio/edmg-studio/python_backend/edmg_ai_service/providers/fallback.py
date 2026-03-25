from __future__ import annotations

import math
import re
from collections import Counter
from typing import Optional

from .base import PlanProvider
from ..schemas import PlanRequest, PlanResponse, PlanVariant, Scene

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has", "have", "if",
    "in", "into", "is", "it", "its", "of", "on", "or", "our", "the", "their", "there", "this",
    "to", "up", "with", "we", "you", "your", "over", "under", "after", "before", "during",
    "chorus", "verse", "bridge", "intro", "outro", "hook",
}

VARIANT_BLUEPRINTS = [
    {
        "name": "Narrative Pulse",
        "logline": "A cinematic performance arc that turns lyrical themes into staged visual chapters.",
        "mood": "cinematic, emotional, performance-driven",
        "palette": ["amber haze", "midnight blue", "silver bloom"],
        "prompt_seed": "cinematic music video frame, coherent hero subject, dramatic lighting, rich texture",
        "camera": ["slow push-in", "parallax drift", "steady handheld glide", "hero close-up"],
        "motion": ["beat-synced light pulses", "slow environmental movement", "subtle cloth motion", "rhythmic camera sway"],
    },
    {
        "name": "Kinetic Geometry",
        "logline": "A rhythm-first visual design built from bold forms, motion, and synchronized scene escalation.",
        "mood": "kinetic, graphic, high-energy",
        "palette": ["neon magenta", "electric cyan", "graphite black"],
        "prompt_seed": "stylized performance tableau, graphic composition, energetic lighting, bold silhouettes",
        "camera": ["snap zoom", "wide tracking shot", "overhead orbit", "low-angle sweep"],
        "motion": ["strobe-synced motion trails", "fast geometric transitions", "impact flashes", "tempo-locked movement"],
    },
    {
        "name": "Atmospheric Drift",
        "logline": "A mood-forward concept built on texture, space, and lyrical symbolism instead of literal performance.",
        "mood": "dreamlike, spacious, textural",
        "palette": ["violet dusk", "deep teal", "soft gold"],
        "prompt_seed": "atmospheric music film frame, layered depth, cinematic haze, detailed environment storytelling",
        "camera": ["floating dolly", "wide reveal", "slow crane move", "locked tableau"],
        "motion": ["ambient particle drift", "fog and light movement", "slow beat-matched transitions", "evolving environmental motion"],
    },
]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z0-9'-]{2,}", (text or "").lower())


def _extract_keywords(req: PlanRequest, *, limit: int = 12) -> list[str]:
    corpus = " ".join(
        filter(
            None,
            [
                req.title or "",
                req.user_notes or "",
                req.style_prefs or "",
                " ".join(req.tags or []),
                req.lyrics or "",
            ],
        )
    )
    counts = Counter(token for token in _tokenize(corpus) if token not in STOPWORDS)
    return [token.replace("-", " ") for token, _count in counts.most_common(limit)]


def _lyrics_sections(lyrics: str | None, scene_count: int) -> list[str]:
    if not lyrics:
        return []
    paragraphs = [chunk.strip() for chunk in re.split(r"\n\s*\n", lyrics) if chunk.strip()]
    if len(paragraphs) >= 2:
        sections = paragraphs
    else:
        lines = [line.strip() for line in lyrics.splitlines() if line.strip()]
        if not lines:
            return []
        chunk_size = max(2, int(math.ceil(len(lines) / max(1, scene_count))))
        sections = [" ".join(lines[index:index + chunk_size]) for index in range(0, len(lines), chunk_size)]
    if len(sections) <= scene_count:
        return sections
    step = len(sections) / float(scene_count)
    return [sections[min(len(sections) - 1, int(index * step))] for index in range(scene_count)]


def _scene_count(req: PlanRequest, duration_s: float) -> int:
    max_scenes = max(3, int(req.max_scenes or 12))
    base = max(3, int(math.ceil(duration_s / 8.0)))
    bpm = float(req.bpm or 0.0)
    if bpm >= 145:
        base += 2
    elif bpm >= 120:
        base += 1
    elif bpm and bpm < 90:
        base = max(3, base - 1)
    return max(3, min(max_scenes, base))


def _scene_windows(duration_s: float, count: int) -> list[tuple[float, float]]:
    count = max(1, count)
    scene_len = duration_s / float(count)
    windows: list[tuple[float, float]] = []
    for index in range(count):
        start = round(index * scene_len, 3)
        end = round(duration_s if index == count - 1 else (index + 1) * scene_len, 3)
        windows.append((start, end))
    return windows


def _palette_from_request(req: PlanRequest, blueprint: dict[str, object]) -> list[str]:
    tags_blob = " ".join(req.tags or []).lower()
    if any(tag in tags_blob for tag in ("techno", "electronic", "edm", "cyber", "synth")):
        return ["neon cyan", "violet pulse", "graphite black"]
    if any(tag in tags_blob for tag in ("ambient", "dream", "cinematic", "ethereal")):
        return ["moonlit blue", "soft gold", "fog white"]
    return list(blueprint["palette"])


def _scene_focus(motifs: list[str], fallback_keywords: list[str], index: int) -> str:
    bank = motifs or fallback_keywords or ["light", "motion", "texture", "silhouette"]
    return bank[index % len(bank)]


def _section_hint(sections: list[str], index: int) -> str:
    if not sections:
        return ""
    return sections[min(index, len(sections) - 1)]


class RuleBasedPlanner(PlanProvider):
    """Deterministic, richer built-in planner.

    This is the zero-download "Director Lite" path: it does not need Ollama or
    any hosted API, but still produces varied scene plans with structure,
    motifs, camera moves, and palette guidance.
    """

    @property
    def name(self) -> str:
        return "rule_based"

    @property
    def model(self) -> Optional[str]:
        return "director_lite"

    def plan(self, req: PlanRequest) -> PlanResponse:
        duration_s = float(req.duration_s) if req.duration_s and req.duration_s > 0 else 60.0
        scene_count = _scene_count(req, duration_s)
        windows = _scene_windows(duration_s, scene_count)
        keywords = _extract_keywords(req)
        sections = _lyrics_sections(req.lyrics, scene_count)
        style_clause = f" Style direction: {req.style_prefs.strip()}." if (req.style_prefs or "").strip() else ""
        title_clause = f" inspired by {req.title.strip()}" if (req.title or "").strip() else ""
        bpm = float(req.bpm or 0.0)
        base_mood = "urgent" if bpm >= 145 else ("driving" if bpm >= 120 else "moody")
        motifs = (req.tags or [])[:6] or keywords[:6]

        variants: list[PlanVariant] = []
        for variant_index in range(req.num_variants):
            blueprint = VARIANT_BLUEPRINTS[variant_index % len(VARIANT_BLUEPRINTS)]
            palette = _palette_from_request(req, blueprint)
            variant_mood = f"{blueprint['mood']}, {base_mood}"
            scenes: list[Scene] = []

            for scene_index, (start_s, end_s) in enumerate(windows):
                focus = _scene_focus(motifs, keywords, scene_index)
                section = _section_hint(sections, scene_index)
                camera = blueprint["camera"][scene_index % len(blueprint["camera"])]
                motion = blueprint["motion"][scene_index % len(blueprint["motion"])]
                energy = (
                    "opening tension"
                    if scene_index == 0
                    else "peak release"
                    if scene_index == len(windows) - 1
                    else "escalating momentum"
                )
                lyric_clause = f" Lyrical cue: {section[:180]}." if section else ""
                prompt = (
                    f"{blueprint['prompt_seed']}{title_clause}, focus on {focus}, {energy}, "
                    f"color palette {', '.join(palette[:3])}, {camera}, {motion}.{style_clause}{lyric_clause}"
                )
                scenes.append(
                    Scene(
                        start_s=start_s,
                        end_s=end_s,
                        prompt=prompt.strip(),
                        negative_prompt="blurry, muddy composition, flat lighting, duplicate subject, watermark, text, logo",
                        camera=camera,
                        motion=motion,
                        notes="Director Lite fallback plan",
                    )
                )

            variants.append(
                PlanVariant(
                    name=str(blueprint["name"]),
                    logline=f"{blueprint['logline']} Free local fallback generated without an external model.",
                    mood=variant_mood,
                    visual_motifs=motifs[:6],
                    color_palette=palette,
                    scenes=scenes,
                )
            )

        return PlanResponse(provider=self.name, model=self.model, variants=variants)
