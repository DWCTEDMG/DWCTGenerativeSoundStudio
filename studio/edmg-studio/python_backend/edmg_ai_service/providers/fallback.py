from __future__ import annotations

import math
import re
from collections import Counter

from ..schemas import PlanRequest, PlanResponse, PlanVariant, Scene
from .base import PlanProvider

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has", "have", "if",
    "in", "into", "is", "it", "its", "of", "on", "or", "our", "the", "their", "there", "this",
    "to", "up", "with", "we", "you", "your", "over", "under", "after", "before", "during",
    "chorus", "verse", "bridge", "intro", "outro", "hook", "one", "same", "keep", "preserve",
    "recognizable", "throughout", "clear", "clearly", "visible", "continuity", "continuous", "exact",
    "boundary", "pose", "scene", "scenes", "camera", "axis", "palette", "geography", "style", "motion",
    "must", "requested",
}

ACTION_VERBS = (
    "crosses", "cross", "walks", "walk", "moves", "move", "turns", "turn", "enters", "enter",
    "runs", "run", "dances", "dance", "performs", "perform", "reaches", "reach", "travels", "travel",
    "drives", "drive", "floats", "float", "flies", "fly", "emerges", "emerge", "steps", "step",
    "raises", "raise", "opens", "open", "closes", "close", "approaches", "approach",
)

ACTION_PROGRESSIVE = {
    "crosses": "crossing",
    "cross": "crossing",
    "walks": "walking",
    "walk": "walking",
    "moves": "moving",
    "move": "moving",
    "turns": "turning",
    "turn": "turning",
    "enters": "entering",
    "enter": "entering",
    "runs": "running",
    "run": "running",
    "dances": "dancing",
    "dance": "dancing",
    "performs": "performing",
    "perform": "performing",
    "reaches": "reaching",
    "reach": "reaching",
    "travels": "traveling",
    "travel": "traveling",
    "drives": "driving",
    "drive": "driving",
    "floats": "floating",
    "float": "floating",
    "flies": "flying",
    "fly": "flying",
    "emerges": "emerging",
    "emerge": "emerging",
    "steps": "stepping",
    "step": "stepping",
    "raises": "raising",
    "raise": "raising",
    "opens": "opening",
    "open": "opening",
    "closes": "closing",
    "close": "closing",
    "approaches": "approaching",
    "approach": "approaching",
}

SETTING_NOUNS = (
    "glasshouse", "conservatory", "greenhouse", "street", "city", "forest", "desert", "room", "stage",
    "warehouse", "shore", "ocean", "temple", "station", "plaza", "corridor", "landscape", "world",
    "apartment", "house", "studio", "tunnel", "bridge", "rooftop", "garden", "field", "alley",
)

VARIANT_BLUEPRINTS = [
    {
        "name": "Narrative Pulse",
        "logline": "A cinematic performance arc that turns lyrical themes into staged visual chapters.",
        "mood": "cinematic, emotional, performance-driven",
        "palette": ["amber haze", "midnight blue", "silver bloom"],
        "prompt_seed": "cinematic music video frame, coherent hero subject, dramatic lighting, rich texture",
        "shot_type": ["wide establishing shot", "tracking medium shot", "profile close-up", "hero resolution shot"],
        "camera": ["slow push-in", "parallax drift", "steady handheld glide", "hero close-up"],
        "action": ["turns toward camera and reaches into the light", "walks through the set with clear screen direction", "raises a hand as the performance intensifies", "settles into a resolved final pose"],
        "motion": ["measured head and hand movement", "purposeful walking with visible stride changes", "expressive gesture and cloth movement", "a controlled breath and final gaze shift"],
        "environment_motion": ["beat-synced practical lights pulse through haze", "foreground fabric and dust drift past the lens", "hair, wardrobe edges, and hanging props react naturally", "the haze thins while the final light slowly settles"],
    },
    {
        "name": "Kinetic Geometry",
        "logline": "A rhythm-first visual design built from bold forms, motion, and synchronized scene escalation.",
        "mood": "kinetic, graphic, high-energy",
        "palette": ["neon magenta", "electric cyan", "graphite black"],
        "prompt_seed": "stylized performance tableau, graphic composition, energetic lighting, bold silhouettes",
        "shot_type": ["graphic establishing wide", "lateral performance medium", "overhead movement shot", "low-angle hero frame"],
        "camera": ["snap zoom", "wide tracking shot", "overhead orbit", "low-angle sweep"],
        "action": ["steps sharply into frame on the downbeat", "crosses the stage through moving geometry", "spins beneath the overhead light grid", "drives forward and stops on the final accent"],
        "motion": ["crisp beat-synced body movement", "fast lateral travel with readable poses", "a complete turn with controlled limb motion", "tempo-locked forward movement and a decisive stop"],
        "environment_motion": ["strobe-synced trails and edge lights pulse", "geometric panels travel in counter-motion", "impact flashes ripple across the floor", "the light grid decelerates into a stable final pattern"],
    },
    {
        "name": "Atmospheric Drift",
        "logline": "A mood-forward concept built on texture, space, and lyrical symbolism instead of literal performance.",
        "mood": "dreamlike, spacious, textural",
        "palette": ["violet dusk", "deep teal", "soft gold"],
        "prompt_seed": "atmospheric music film frame, layered depth, cinematic haze, detailed environment storytelling",
        "shot_type": ["atmospheric establishing wide", "layered medium-wide", "slow profile portrait", "negative-space resolution frame"],
        "camera": ["floating dolly", "wide reveal", "slow crane move", "restrained lateral drift"],
        "action": ["emerges slowly from the haze", "moves between foreground layers", "looks upward as the space opens", "comes to rest while the world continues breathing"],
        "motion": ["subtle walking and breathing movement", "gentle body turns with continuous screen direction", "a gradual gaze and posture change", "a small final gesture and natural breathing"],
        "environment_motion": ["ambient particles drift at different depths", "fog and reflected light travel across the set", "fabric, branches, and distant atmosphere move slowly", "soft gold light and haze continue beyond the final gesture"],
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
    max_scenes = max(1, int(req.max_scenes or 12))
    base = max(3, int(math.ceil(duration_s / 8.0)))
    bpm = float(req.bpm or 0.0)
    if bpm >= 145:
        base += 2
    elif bpm >= 120:
        base += 1
    elif bpm and bpm < 90:
        base = max(3, base - 1)
    return max(1, min(max_scenes, base))


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
    request_blob = " ".join(
        [
            *(req.tags or []),
            req.style_prefs or "",
            req.user_notes or "",
        ]
    ).lower()
    requested_colors = [
        color
        for color in (
            "copper",
            "moonlit blue",
            "midnight blue",
            "electric cyan",
            "neon magenta",
            "petrol green",
            "deep teal",
            "violet",
            "crimson",
            "amber",
            "silver",
            "gold",
            "graphite black",
            "fog white",
        )
        if color in request_blob
    ]
    if requested_colors:
        return list(dict.fromkeys([*requested_colors, *list(blueprint["palette"])]))[:3]
    if any(tag in request_blob for tag in ("techno", "electronic", "edm", "cyber", "synth")):
        return ["neon cyan", "violet pulse", "graphite black"]
    if any(tag in request_blob for tag in ("ambient", "dream", "cinematic", "ethereal")):
        return ["moonlit blue", "soft gold", "fog white"]
    return list(blueprint["palette"])


def _scene_focus(motifs: list[str], fallback_keywords: list[str], index: int) -> str:
    bank = motifs or fallback_keywords or ["light", "motion", "texture", "silhouette"]
    return bank[index % len(bank)]


def _section_hint(sections: list[str], index: int) -> str:
    if not sections:
        return ""
    return sections[min(index, len(sections) - 1)]


def _first_sentence(text: str | None) -> str:
    return re.split(r"(?<=[.!?])\s+", str(text or "").strip(), maxsplit=1)[0].strip()


def _explicit_subject(req: PlanRequest) -> str:
    sentence = _first_sentence(req.user_notes)
    if not sentence:
        return ""
    sentence = re.sub(
        r"^(?:please\s+)?(?:keep|follow|feature|show|depict|preserve|use)\s+",
        "",
        sentence,
        flags=re.IGNORECASE,
    )
    action_pattern = "|".join(re.escape(verb) for verb in ACTION_VERBS)
    match = re.match(
        rf"(.+?)(?=\s+(?:{action_pattern}|recognizable|consistent|unchanged)\b|[,;.]|$)",
        sentence,
        flags=re.IGNORECASE,
    )
    subject = " ".join(str(match.group(1) if match else "").split()).strip(" ,;:.-")
    if len(subject.split()) < 2 or len(subject) > 220:
        return ""
    return subject


def _persistent_signature_props(req: PlanRequest, subject: str) -> list[str]:
    notes = " ".join(str(req.user_notes or "").split())
    if not notes:
        return []
    match = re.search(
        r"\b(?:preserve|keep)\s+(.+?)\s+(?:throughout|across\s+(?:all|every)\s+scenes?|in\s+every\s+scene)\b",
        notes,
        flags=re.IGNORECASE,
    )
    if not match:
        return []

    subject_lower = subject.lower()
    props: list[str] = []
    for raw_part in re.split(r"\s+and\s+|,", match.group(1), flags=re.IGNORECASE):
        part = re.sub(r"^(?:the\s+)?same\s+", "", raw_part.strip(), flags=re.IGNORECASE)
        part = part.strip(" ,;:.-")
        if not part or len(part.split()) > 8:
            continue
        normalized = part.lower()
        if normalized in subject_lower or any(
            token in subject_lower for token in normalized.split() if len(token) >= 5
        ):
            continue
        if normalized not in {item.lower() for item in props}:
            props.append(part)
    return props


def _explicit_action(req: PlanRequest) -> str:
    sentence = _first_sentence(req.user_notes)
    if not sentence:
        return ""
    action_pattern = "|".join(re.escape(verb) for verb in ACTION_VERBS)
    match = re.search(rf"\b(?:{action_pattern})\b", sentence, flags=re.IGNORECASE)
    if not match:
        return ""
    return " ".join(sentence[match.start():].strip(" ,;:.-").split())[:300]


def _explicit_setting(req: PlanRequest, motifs: list[str]) -> str:
    notes = str(req.user_notes or "")
    setting_pattern = "|".join(re.escape(noun) for noun in SETTING_NOUNS)
    matches = list(
        re.finditer(
            rf"\b((?:one|a|an|the)\s+(?:[a-zA-Z0-9'-]+\s+){{0,5}}(?:{setting_pattern}))\b",
            notes,
            flags=re.IGNORECASE,
        )
    )
    if matches:
        return " ".join(matches[-1].group(1).split())
    for motif in motifs:
        if re.search(rf"\b(?:{setting_pattern})\b", str(motif), flags=re.IGNORECASE):
            return " ".join(str(motif).split())
    return ""


def _subject_anchor(req: PlanRequest, motifs: list[str], keywords: list[str]) -> str:
    explicit = _explicit_subject(req)
    if explicit:
        props = _persistent_signature_props(req, explicit)
        prop_clause = f" carrying {' and '.join(props)}" if props else ""
        return (
            f"{explicit}{prop_clause}; identical face, silhouette, wardrobe, defining features, and "
            "signature props in every scene"
        )
    focus = _scene_focus(motifs, keywords, 0)
    title = str(req.title or "").strip()
    title_hint = f" from {title}" if title else ""
    return (
        f"one recurring lead subject{title_hint}, visually associated with {focus}, "
        "with the same face, silhouette, wardrobe, and signature prop"
    )


def _setting_anchor(req: PlanRequest, motifs: list[str], keywords: list[str]) -> str:
    focus = _explicit_setting(req, motifs) or _scene_focus(motifs, keywords, 0)
    direction = (
        "the east entry, central landmark, and west exit"
        if re.search(r"\beast\s*(?:-|to)\s*west\b", str(req.user_notes or ""), flags=re.IGNORECASE)
        else "the recurring entry, central, and exit landmarks"
    )
    return (
        f"{focus} as one geographically continuous cinematic world; preserve {direction}, stable "
        "spatial relationships, and a consistent left-to-right screen axis"
    )


def _setting_for_scene(setting_lock: str, scene_index: int, scene_count: int) -> str:
    if scene_count <= 1:
        phase = "the single continuous action area"
    elif scene_index <= 0:
        phase = "the opening area beside the entry landmark"
    elif scene_index >= scene_count - 1:
        phase = "the resolving area beside the exit landmark"
    else:
        phase = "the central area beside the recurring middle landmark"
    return f"{setting_lock}; this shot occupies {phase}"


def _style_lock(
    blueprint: dict[str, object],
    palette: list[str],
    style_prefs: str | None,
) -> str:
    requested_style = " ".join(str(style_prefs or "").split())
    requested_clause = f"{requested_style}; " if requested_style else ""
    return (
        f"{requested_clause}{blueprint['mood']} visual finish; {', '.join(palette[:3])} palette; "
        "consistent medium, texture, lighting logic, lens family, contrast, and aspect ratio"
    )


def _scene_action(
    authored_action: str,
    fallback_action: str,
    *,
    scene_index: int,
    scene_count: int,
) -> str:
    if not authored_action:
        return fallback_action
    action_parts = authored_action.split(maxsplit=1)
    first_word = action_parts[0].lower()
    rest = f" {action_parts[1]}" if len(action_parts) > 1 else ""
    progressive = f"{ACTION_PROGRESSIVE.get(first_word, first_word)}{rest}"
    if scene_count <= 1:
        return authored_action
    if scene_index <= 0:
        return f"begins {progressive} and completes the opening portion without a pose reset"
    if scene_index >= scene_count - 1:
        return f"completes {progressive} and settles into a readable final pose"
    return f"continues {progressive} without teleporting or reversing direction"


def _opening_state(subject: str, setting: str) -> str:
    return (
        f"First frame: {subject}. The lead holds a readable starting pose inside {setting}, with the "
        "body oriented left-to-right and the camera settled before continuous movement begins"
    )


def _ending_state(
    subject: str,
    setting: str,
    action: str,
    *,
    scene_index: int,
    scene_count: int,
) -> str:
    if scene_index >= scene_count - 1:
        return (
            f"Final frame: {subject}. The action has visibly resolved ({action}); the lead holds a "
            f"readable final pose inside {setting}. Identity, wardrobe, landmark placement, and camera "
            "axis remain stable while natural motion settles"
        )
    return (
        f"Handoff frame: {subject}. The action reaches a visible intermediate result ({action}); the "
        f"lead remains inside {setting}, oriented left-to-right in a readable handoff pose with camera "
        "axis and landmark placement preserved"
    )


def _continuity_instruction(subject: str, scene_index: int) -> str:
    if scene_index == 0:
        return f"establish {subject}; keep one subject only and establish left-to-right screen direction"
    return (
        f"continue {subject}; preserve identity, wardrobe, palette, world, and screen direction "
        "while advancing the action from the previous scene"
    )


def _transition_instruction(scene_index: int, scene_count: int, bpm: float) -> str:
    if scene_index == 0:
        return "opening composition with a readable starting pose"
    if scene_index == scene_count - 1:
        return "match-action dissolve into the resolved final image"
    if bpm >= 125 and scene_index % 3 == 0:
        return "motivated impact cut on the downbeat with screen direction preserved"
    return "match-action continuation carried by the subject gesture and environment movement"


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
    def model(self) -> str | None:
        return "director_lite"

    def plan(self, req: PlanRequest) -> PlanResponse:
        duration_s = float(req.duration_s) if req.duration_s and req.duration_s > 0 else 60.0
        scene_count = _scene_count(req, duration_s)
        windows = _scene_windows(duration_s, scene_count)
        keywords = _extract_keywords(req)
        sections = _lyrics_sections(req.lyrics, scene_count)
        style_clause = f" Style direction: {req.style_prefs.strip()}." if (req.style_prefs or "").strip() else ""
        notes_clause = (
            f" Director constraints: {' '.join(req.user_notes.split())[:400]}."
            if (req.user_notes or "").strip()
            else ""
        )
        title_clause = f" inspired by {req.title.strip()}" if (req.title or "").strip() else ""
        bpm = float(req.bpm or 0.0)
        base_mood = "urgent" if bpm >= 145 else ("driving" if bpm >= 120 else "moody")
        motifs = (req.tags or [])[:6] or keywords[:6]

        variants: list[PlanVariant] = []
        for variant_index in range(req.num_variants):
            blueprint = VARIANT_BLUEPRINTS[variant_index % len(VARIANT_BLUEPRINTS)]
            palette = _palette_from_request(req, blueprint)
            variant_mood = f"{blueprint['mood']}, {base_mood}"
            character_lock = _subject_anchor(req, motifs, keywords)
            setting_lock = _setting_anchor(req, motifs, keywords)
            style_lock = _style_lock(blueprint, palette, req.style_prefs)
            authored_action = _explicit_action(req)
            previous_end_state = ""
            scenes: list[Scene] = []

            for scene_index, (start_s, end_s) in enumerate(windows):
                focus = _scene_focus(motifs, keywords, scene_index)
                section = _section_hint(sections, scene_index)
                shot_type = blueprint["shot_type"][scene_index % len(blueprint["shot_type"])]
                camera = blueprint["camera"][scene_index % len(blueprint["camera"])]
                action = _scene_action(
                    authored_action,
                    blueprint["action"][scene_index % len(blueprint["action"])],
                    scene_index=scene_index,
                    scene_count=len(windows),
                )
                motion = blueprint["motion"][scene_index % len(blueprint["motion"])]
                environment_motion = blueprint["environment_motion"][
                    scene_index % len(blueprint["environment_motion"])
                ]
                setting = _setting_for_scene(setting_lock, scene_index, len(windows))
                start_state = previous_end_state or _opening_state(character_lock, setting)
                end_state = _ending_state(
                    character_lock,
                    setting,
                    action,
                    scene_index=scene_index,
                    scene_count=len(windows),
                )
                previous_end_state = end_state
                continuity = _continuity_instruction(character_lock, scene_index)
                transition = _transition_instruction(scene_index, len(windows), bpm)
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
                    f"color palette {', '.join(palette[:3])}. Setting: {setting}. Shot type: {shot_type}. "
                    f"Visible action: {action}. Subject motion: {motion}. Environment motion: {environment_motion}. "
                    f"Camera path: {camera}. Character lock: {character_lock}. Style lock: {style_lock}. "
                    f"Start state: {start_state}. End state: {end_state}. Continuity: {continuity}. "
                    f"Transition: {transition}.{style_clause}{notes_clause}{lyric_clause}"
                )
                scenes.append(
                    Scene(
                        start_s=start_s,
                        end_s=end_s,
                        prompt=prompt.strip(),
                        negative_prompt=(
                            "still frame, frozen pose, slideshow, collage, split screen, storyboard sheet, "
                            "blurry, muddy composition, flat lighting, duplicate subject, identity drift, "
                            "wardrobe change, style drift, location jump, landmark drift, camera teleport, "
                            "discontinuous action, conflicting camera moves, broken anatomy, watermark, text, logo"
                        ),
                        setting=setting,
                        shot_type=shot_type,
                        character_lock=character_lock,
                        style_lock=style_lock,
                        start_state=start_state,
                        end_state=end_state,
                        subject=character_lock,
                        action=action,
                        camera=camera,
                        motion=motion,
                        environment_motion=environment_motion,
                        continuity=continuity,
                        transition=transition,
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
