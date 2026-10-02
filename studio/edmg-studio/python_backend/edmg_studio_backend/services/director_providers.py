"""Provider adapters and orchestration for Nemotron Director and Cosmos evidence."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

import requests
from pydantic import ValidationError

from ..domain.director_plan import (
    COSMOS_MODEL_ID,
    NEMOTRON_MODEL_ID,
    DirectorPlan,
    SpecialistRequest,
    SpecialistResult,
    validate_plan_locks,
)
from ..domain.director_scene import DirectorDocument


class DirectorProvider(Protocol):
    def plan(
        self, *, context: dict[str, Any], instruction: str, mode: str,
        specialist_results: list[SpecialistResult], correlation_id: str,
    ) -> DirectorPlan: ...


class SpecialistProvider(Protocol):
    def analyze(self, request: SpecialistRequest) -> SpecialistResult: ...


@dataclass(frozen=True)
class ProviderEndpoint:
    endpoint: str
    model: str
    api_key: str = ""
    timeout_s: float = 180.0

    @property
    def chat_url(self) -> str:
        return self.endpoint.rstrip("/") + "/chat/completions"


def _content(response: requests.Response) -> str:
    response.raise_for_status()
    payload = response.json()
    value = payload["choices"][0]["message"]["content"]
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Provider returned an empty response")
    text = value.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return text


class OpenAICompatibleNemotronProvider:
    def __init__(self, config: ProviderEndpoint):
        self.config = config

    def _request(self, messages: list[dict[str, str]]) -> str:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        response = requests.post(
            self.config.chat_url,
            headers=headers,
            json={"model": self.config.model, "messages": messages, "temperature": 0.2,
                  "response_format": {"type": "json_object"}},
            timeout=self.config.timeout_s,
        )
        return _content(response)

    def plan(
        self, *, context: dict[str, Any], instruction: str, mode: str,
        specialist_results: list[SpecialistResult], correlation_id: str,
    ) -> DirectorPlan:
        system = (
            "You are the EDMG Director. Return only JSON matching DirectorPlan schema version 1.0. "
            "You propose a complete DirectorDocument but never mutate state, execute commands, choose "
            "arbitrary paths, or make network calls. Respect locked scenes and timeline locks. Cosmos "
            "results are non-authoritative evidence. director_model must identify the active model."
        )
        request = {
            "schema_version": "1.0", "correlation_id": correlation_id, "mode": mode,
            "instruction": instruction, "context": context,
            "specialist_results": [item.model_dump(mode="json") for item in specialist_results],
            "required_shape": {
                "schema_version": "1.0", "correlation_id": correlation_id,
                "director_model": self.config.model, "mode": mode,
                "document": "complete DirectorDocument", "decisions": [],
                "specialist_results": [], "diagnostics": {},
            },
        }
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(request, separators=(",", ":"))}]
        raw = self._request(messages)
        try:
            plan = DirectorPlan.model_validate_json(raw)
        except (ValidationError, ValueError, json.JSONDecodeError) as first_error:
            repair = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"Repair this response to the required JSON schema. Validation error: {first_error}"},
            ]
            plan = DirectorPlan.model_validate_json(self._request(repair))
        return validate_plan_locks(plan, context)


class OpenAICompatibleCosmosProvider:
    def __init__(self, config: ProviderEndpoint):
        self.config = config

    def analyze(self, request: SpecialistRequest) -> SpecialistResult:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        response = requests.post(
            self.config.chat_url, headers=headers,
            json={
                "model": self.config.model, "temperature": 0.1,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "Return only SpecialistResult JSON version 1.0. Supply evidence, never commands or project mutations."},
                    {"role": "user", "content": request.model_dump_json()},
                ],
            }, timeout=self.config.timeout_s,
        )
        return SpecialistResult.model_validate_json(_content(response))


def should_route_cosmos(mode: str, routing: str, context: dict[str, Any]) -> bool:
    if mode != "advanced" or routing == "off":
        return False
    if routing == "always_video":
        return True
    return bool(context.get("video_assets") or context.get("reference_video") or context.get("motion_complexity") == "high")


def run_nemotron_director_job(
    payload: dict[str, Any], *, progress_fn=None,
) -> dict[str, Any]:
    settings = dict(payload.get("director_provider_settings") or {})
    endpoint = str(settings.get("primary_endpoint") or "").strip()
    if not endpoint:
        raise ValueError("Nemotron Director endpoint is not configured")
    correlation_id = str(payload.get("correlation_id") or uuid4())
    mode = str(payload.get("director_quality") or "standard")
    context = {
        "source_document": payload["document"],
        "timeline": payload.get("timeline_context") or {},
        "audio_evidence": payload.get("audio_evidence") or {},
        "story_bible": payload.get("story_bible") or {},
        "locked_scene_ids": payload.get("locked_scene_ids") or [],
        "video_assets": payload.get("video_assets") or [],
    }
    specialist_results: list[SpecialistResult] = []
    cosmos_status = "skipped"
    cosmos_error = None
    started = time.monotonic()
    if bool(settings.get("specialist_enabled", True)) and should_route_cosmos(
        mode, str(settings.get("specialist_routing") or "automatic"), context
    ):
        if progress_fn:
            progress_fn("specialist", "Requesting Cosmos video specialist evidence")
        try:
            cosmos_endpoint = str(settings.get("specialist_endpoint") or "").strip()
            if not cosmos_endpoint:
                raise ValueError("Cosmos endpoint is not configured")
            specialist = OpenAICompatibleCosmosProvider(ProviderEndpoint(
                cosmos_endpoint, str(settings.get("specialist_model") or COSMOS_MODEL_ID),
                os.getenv("EDMG_COSMOS_API_KEY", ""), float(settings.get("timeout_s") or 180),
            ))
            specialist_results.append(specialist.analyze(SpecialistRequest(
                request_id=correlation_id + ":cosmos", task="video_analysis",
                instruction=str(payload["instruction"]), context=context,
            )))
            cosmos_status = "used"
        except (requests.RequestException, ValueError, ValidationError, KeyError) as exc:
            cosmos_status, cosmos_error = "unavailable", str(exc)
    if progress_fn:
        progress_fn("generating", "Generating the authoritative Nemotron DirectorPlan")
    primary_model = str(settings.get("primary_model") or NEMOTRON_MODEL_ID)
    provider = OpenAICompatibleNemotronProvider(ProviderEndpoint(
        endpoint, primary_model,
        os.getenv("EDMG_NEMOTRON_API_KEY", ""), float(settings.get("timeout_s") or 180),
    ))
    plan = provider.plan(context=context, instruction=str(payload["instruction"]), mode=mode,
                         specialist_results=specialist_results, correlation_id=correlation_id)
    latency_ms = round((time.monotonic() - started) * 1000)
    return {
        "status": "draft", "document": plan.document.model_dump(mode="json"),
        "director_plan": plan.model_dump(mode="json"), "source_revision": payload["source_revision"],
        "provenance": {
            "provider": "nemotron", "model_id": primary_model,
            "correlation_id": correlation_id, "mode": mode, "plan_validation": "passed",
            "specialist": {"model_id": settings.get("specialist_model", COSMOS_MODEL_ID),
                           "status": cosmos_status, "error": cosmos_error},
            "latency_ms": latency_ms,
        },
    }
