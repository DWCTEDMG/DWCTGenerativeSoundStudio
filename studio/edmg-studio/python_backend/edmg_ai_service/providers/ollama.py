from __future__ import annotations

import json
import re

import requests

from ..schemas import PlanRequest, PlanResponse, PlanVariant
from .base import PlanProvider
from .fallback import RuleBasedPlanner
from .storyboard_contract import storyboard_system_prompt

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict | None:
    # Try entire response
    try:
        return json.loads(text)
    except Exception:
        pass

    # Try to extract a JSON object embedded in text
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


class OllamaPlanner(PlanProvider):
    def __init__(self, base_url: str, model: str, timeout_s: float = 180.0):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_s = timeout_s
        self._fallback = RuleBasedPlanner()

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def model(self) -> str | None:
        return self._model

    def plan(self, req: PlanRequest) -> PlanResponse:
        system = storyboard_system_prompt()

        ctx = {
            "title": req.title,
            "duration_s": req.duration_s,
            "bpm": req.bpm,
            "tags": req.tags,
            "user_notes": req.user_notes,
            "style_prefs": req.style_prefs,
            "lyrics": (req.lyrics[:2000] if req.lyrics else None),
            "num_variants": req.num_variants,
            "max_scenes": req.max_scenes,
        }

        prompt = (
            "Input JSON:\n"
            + json.dumps(ctx, ensure_ascii=False)
            + "\n\n"
            "Produce EDMG variants. Ensure scene times cover [0,duration_s] when duration_s is provided. "
            "Keep prompts vivid and filmable, with an explicit subject identity, visible action, "
            "environment movement, camera move, continuity rule, and transition for every scene. "
            "If lyrics exist, align scenes to themes and musical sections."
        )

        try:
            r = requests.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "system": system,
                    "stream": False,
                },
                timeout=self._timeout_s,
            )
            r.raise_for_status()
            data = r.json()
            text = data.get("response", "")
        except Exception:
            return self._fallback.plan(req)

        obj = _extract_json(text)
        if not obj or "variants" not in obj:
            return self._fallback.plan(req)

        # Let pydantic validate/coerce shapes
        try:
            variants = [PlanVariant.model_validate(v) for v in obj["variants"]]
            return PlanResponse(provider=self.name, model=self._model, variants=variants)
        except Exception:
            return self._fallback.plan(req)
