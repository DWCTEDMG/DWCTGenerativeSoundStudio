from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request

from ..errors import UserFacingError
from ..schemas import HealthResponse


@dataclass(frozen=True)
class SystemSettingsDependencies:
    security_status: Callable[[str, str | None], dict[str, Any]]
    render_profiles: Callable[[], dict[str, Any]]
    hardware: Callable[[], dict[str, Any]]
    render_plan: Callable[[dict[str, Any]], dict[str, Any]]
    render_provider_status: Callable[[], dict[str, Any]]
    update_render_settings: Callable[[dict[str, Any]], dict[str, Any]]
    invalidate_hardware: Callable[[], None]
    transcription_status: Callable[[], dict[str, Any]]
    update_transcription_settings: Callable[[dict[str, Any]], dict[str, Any]]
    config_payload: Callable[[], dict[str, Any]]
    secrets_status_payload: Callable[[], dict[str, Any]]
    set_secret: Callable[[str, str], None]
    clear_secret: Callable[[str], None]
    allowed_secrets: frozenset[str]
    codex_status: Callable[[], dict[str, Any]]


def create_system_settings_router(deps: SystemSettingsDependencies) -> APIRouter:
    router = APIRouter(tags=["system", "settings"])

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(ok=True)

    @router.get("/v1/security/status")
    def backend_security_status(request: Request):
        return deps.security_status(request.url.scheme, (request.scope.get("server") or (None,))[0])

    @router.get("/v1/settings/render_profiles")
    def render_profiles():
        return deps.render_profiles()

    @router.get("/v1/hardware")
    def hardware():
        profile = deps.hardware()
        return {"ok": True, "hardware": profile, "render_tier_plan": deps.render_plan(profile)}

    @router.get("/v1/settings/render_providers")
    def get_render_providers():
        return deps.render_provider_status()

    @router.post("/v1/settings/render_providers")
    def set_render_providers(payload: dict[str, Any]):
        saved = deps.update_render_settings(payload)
        deps.invalidate_hardware()
        return {"ok": True, "settings": saved, "status": deps.render_provider_status()}

    @router.get("/v1/settings/transcription")
    def get_transcription_settings():
        return deps.transcription_status()

    @router.post("/v1/settings/transcription")
    def set_transcription_settings(payload: dict[str, Any]):
        saved = deps.update_transcription_settings(payload)
        return {"ok": True, "settings": saved, "status": deps.transcription_status()}

    @router.get("/v1/codex/status")
    def get_codex_status():
        return deps.codex_status()

    @router.get("/v1/config")
    def get_config():
        return deps.config_payload()

    @router.get("/v1/settings/secrets/status")
    def secrets_status():
        return deps.secrets_status_payload()

    @router.post("/v1/settings/secrets/set")
    def secrets_set(payload: dict[str, Any]):
        name = str((payload or {}).get("name") or "").strip().lower()
        value = str((payload or {}).get("value") or "")
        if name not in deps.allowed_secrets:
            raise UserFacingError(
                "Unknown secret", hint=f"Supported: {', '.join(sorted(deps.allowed_secrets))}"
            )
        if not value:
            raise UserFacingError(
                "Missing value", hint="Paste the token/key value, then click Save."
            )
        deps.set_secret(name, value)
        return {"ok": True}

    @router.post("/v1/settings/secrets/clear")
    def secrets_clear(payload: dict[str, Any]):
        name = str((payload or {}).get("name") or "").strip().lower()
        if name not in deps.allowed_secrets:
            raise UserFacingError(
                "Unknown secret", hint=f"Supported: {', '.join(sorted(deps.allowed_secrets))}"
            )
        deps.clear_secret(name)
        return {"ok": True}

    return router
