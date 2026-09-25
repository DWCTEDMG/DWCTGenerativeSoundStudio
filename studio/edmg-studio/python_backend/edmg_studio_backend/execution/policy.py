"""Pure execution-environment selection for Studio render requests."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .contracts import (
    ExecutionEnvironment,
    ExecutionPreference,
    ResolvedExecutionEnvironment,
    RuntimeProfile,
)

LocalExecutionEnvironment = Literal["windows", "wsl"]


class PolicyModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExecutionRequestContext(PolicyModel):
    engine: str = Field(min_length=1, max_length=160)
    preference: ExecutionPreference = Field(default_factory=ExecutionPreference)
    requires_gpu: bool = True


class ExecutionSettings(PolicyModel):
    runtime_profile: RuntimeProfile = "standard"
    model_environment_preferences: dict[str, LocalExecutionEnvironment] = Field(
        default_factory=dict,
        max_length=256,
    )


class ExecutionCapabilities(PolicyModel):
    supported_environments: dict[str, frozenset[ResolvedExecutionEnvironment]] = Field(
        default_factory=dict,
        max_length=256,
    )
    gpu_environments: frozenset[ResolvedExecutionEnvironment] = Field(default_factory=frozenset)

    def environments_for(self, engine: str) -> frozenset[ResolvedExecutionEnvironment]:
        return self.supported_environments.get(engine, frozenset())


class ExecutionResolution(PolicyModel):
    requested_environment: ExecutionEnvironment
    resolved_environment: ResolvedExecutionEnvironment | None = None
    reason_code: str = Field(min_length=1, max_length=160)
    fallback_applied: bool = False
    blocked: bool = False


def _is_usable(
    environment: ResolvedExecutionEnvironment,
    request: ExecutionRequestContext,
    capabilities: ExecutionCapabilities,
    supported: frozenset[ResolvedExecutionEnvironment],
) -> bool:
    return environment in supported and (
        not request.requires_gpu or environment in capabilities.gpu_environments
    )


def _blocked(requested: ExecutionEnvironment, reason: str) -> ExecutionResolution:
    return ExecutionResolution(
        requested_environment=requested,
        reason_code=reason,
        blocked=True,
    )


def resolve_execution_environment(
    request: ExecutionRequestContext,
    settings: ExecutionSettings,
    capabilities: ExecutionCapabilities,
) -> ExecutionResolution:
    """Resolve execution without probing processes or mutating runtime state."""

    requested = request.preference.environment
    supported = capabilities.environments_for(request.engine)

    if settings.runtime_profile == "external_linux" or requested == "external":
        return _blocked(requested, "EXTERNAL_BACKEND_CLIENT_ONLY")

    if requested in {"windows", "wsl"}:
        if requested not in supported:
            return _blocked(requested, "EXPLICIT_ENVIRONMENT_UNAVAILABLE")
        if request.requires_gpu and requested not in capabilities.gpu_environments:
            return _blocked(requested, "GPU_ENVIRONMENT_UNAVAILABLE")
        return ExecutionResolution(
            requested_environment=requested,
            resolved_environment=requested,
            reason_code="EXPLICIT_ENVIRONMENT",
        )

    saved_preference = settings.model_environment_preferences.get(request.engine)
    if saved_preference is not None:
        if _is_usable(saved_preference, request, capabilities, supported):
            return ExecutionResolution(
                requested_environment=requested,
                resolved_environment=saved_preference,
                reason_code="MODEL_ENVIRONMENT_PREFERENCE",
            )
        if not request.preference.allow_environment_fallback:
            return _blocked(requested, "ENVIRONMENT_FALLBACK_DISABLED")

    if settings.runtime_profile == "standard":
        if _is_usable("windows", request, capabilities, supported):
            return ExecutionResolution(
                requested_environment=requested,
                resolved_environment="windows",
                reason_code="STANDARD_WINDOWS_DEFAULT",
                fallback_applied=saved_preference is not None,
            )
        if request.requires_gpu and "windows" in supported:
            return _blocked(requested, "GPU_ENVIRONMENT_UNAVAILABLE")
        return _blocked(requested, "STANDARD_WINDOWS_UNAVAILABLE")

    preferred: LocalExecutionEnvironment = (
        "wsl" if request.engine == "hunyuan_video15" else "windows"
    )
    if saved_preference is None and _is_usable(preferred, request, capabilities, supported):
        return ExecutionResolution(
            requested_environment=requested,
            resolved_environment=preferred,
            reason_code=(
                "LINUX_FIRST_ENGINE" if preferred == "wsl" else "WINDOWS_ENGINE_DEFAULT"
            ),
        )

    if saved_preference is None and not request.preference.allow_environment_fallback:
        return _blocked(requested, "ENVIRONMENT_FALLBACK_DISABLED")

    for candidate in ("windows", "wsl"):
        if candidate == saved_preference:
            continue
        if _is_usable(candidate, request, capabilities, supported):
            return ExecutionResolution(
                requested_environment=requested,
                resolved_environment=candidate,
                reason_code=(
                    "MODEL_ENVIRONMENT_FALLBACK"
                    if saved_preference is not None
                    else "AUTOMATIC_ENVIRONMENT_FALLBACK"
                ),
                fallback_applied=True,
            )

    if request.requires_gpu and any(environment in supported for environment in ("windows", "wsl")):
        return _blocked(requested, "GPU_ENVIRONMENT_UNAVAILABLE")
    return _blocked(requested, "EXECUTION_ENVIRONMENT_UNAVAILABLE")
