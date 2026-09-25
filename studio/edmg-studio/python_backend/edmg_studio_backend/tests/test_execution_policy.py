from __future__ import annotations

import json

import pytest

from edmg_studio_backend.execution.contracts import ExecutionPreference
from edmg_studio_backend.execution.policy import (
    ExecutionCapabilities,
    ExecutionRequestContext,
    ExecutionSettings,
    resolve_execution_environment,
)
from edmg_studio_backend.services.render_settings import RenderSettingsStore


def _capabilities(
    *,
    hunyuan: tuple[str, ...] = ("wsl",),
    ltx: tuple[str, ...] = ("windows", "wsl"),
) -> ExecutionCapabilities:
    return ExecutionCapabilities(
        supported_environments={
            "hunyuan_video15": frozenset(hunyuan),
            "ltx_25": frozenset(ltx),
        },
        gpu_environments=frozenset({"windows", "wsl"}),
    )


@pytest.mark.parametrize(
    ("profile", "engine", "preference", "expected", "reason"),
    [
        ("standard", "ltx_25", "auto", "windows", "STANDARD_WINDOWS_DEFAULT"),
        ("hybrid_gpu", "ltx_25", "auto", "windows", "WINDOWS_ENGINE_DEFAULT"),
        ("hybrid_gpu", "hunyuan_video15", "auto", "wsl", "LINUX_FIRST_ENGINE"),
        ("standard", "ltx_25", "wsl", "wsl", "EXPLICIT_ENVIRONMENT"),
        ("hybrid_gpu", "ltx_25", "windows", "windows", "EXPLICIT_ENVIRONMENT"),
    ],
)
def test_policy_resolves_supported_profiles_and_preferences(
    profile: str,
    engine: str,
    preference: str,
    expected: str,
    reason: str,
) -> None:
    resolution = resolve_execution_environment(
        ExecutionRequestContext(
            engine=engine,
            preference=ExecutionPreference(environment=preference),
        ),
        ExecutionSettings(runtime_profile=profile),
        _capabilities(),
    )

    assert resolution.resolved_environment == expected
    assert resolution.reason_code == reason
    assert not resolution.blocked


def test_standard_auto_never_starts_wsl_when_windows_is_unavailable() -> None:
    resolution = resolve_execution_environment(
        ExecutionRequestContext(engine="hunyuan_video15"),
        ExecutionSettings(runtime_profile="standard"),
        _capabilities(),
    )

    assert resolution.blocked
    assert resolution.resolved_environment is None
    assert resolution.reason_code == "STANDARD_WINDOWS_UNAVAILABLE"


@pytest.mark.parametrize("preference", ["windows", "wsl", "external"])
def test_explicit_unsupported_or_external_selection_fails(preference: str) -> None:
    resolution = resolve_execution_environment(
        ExecutionRequestContext(
            engine="hunyuan_video15",
            preference=ExecutionPreference(environment=preference),
        ),
        ExecutionSettings(runtime_profile="hybrid_gpu"),
        _capabilities(),
    )

    if preference == "wsl":
        assert not resolution.blocked
        assert resolution.resolved_environment == "wsl"
    else:
        assert resolution.blocked
        assert resolution.resolved_environment is None
        assert resolution.reason_code in {
            "EXPLICIT_ENVIRONMENT_UNAVAILABLE",
            "EXTERNAL_BACKEND_CLIENT_ONLY",
        }


def test_external_linux_profile_is_not_a_local_worker_selection() -> None:
    resolution = resolve_execution_environment(
        ExecutionRequestContext(engine="hunyuan_video15"),
        ExecutionSettings(runtime_profile="external_linux"),
        _capabilities(),
    )

    assert resolution.blocked
    assert resolution.reason_code == "EXTERNAL_BACKEND_CLIENT_ONLY"


def test_model_preference_is_used_for_auto_and_fallback_is_explicit() -> None:
    settings = ExecutionSettings(
        runtime_profile="hybrid_gpu",
        model_environment_preferences={"ltx_25": "wsl"},
    )
    preferred = resolve_execution_environment(
        ExecutionRequestContext(engine="ltx_25"),
        settings,
        _capabilities(ltx=("windows", "wsl")),
    )
    fallback = resolve_execution_environment(
        ExecutionRequestContext(engine="ltx_25"),
        settings,
        _capabilities(ltx=("windows",)),
    )

    assert preferred.resolved_environment == "wsl"
    assert preferred.reason_code == "MODEL_ENVIRONMENT_PREFERENCE"
    assert fallback.resolved_environment == "windows"
    assert fallback.fallback_applied
    assert fallback.reason_code == "MODEL_ENVIRONMENT_FALLBACK"


def test_no_fallback_rejects_environment_change() -> None:
    resolution = resolve_execution_environment(
        ExecutionRequestContext(
            engine="ltx_25",
            preference=ExecutionPreference(
                environment="auto",
                allow_environment_fallback=False,
            ),
        ),
        ExecutionSettings(
            runtime_profile="hybrid_gpu",
            model_environment_preferences={"ltx_25": "wsl"},
        ),
        _capabilities(ltx=("windows",)),
    )

    assert resolution.blocked
    assert resolution.reason_code == "ENVIRONMENT_FALLBACK_DISABLED"


def test_gpu_request_never_falls_back_to_non_gpu_environment() -> None:
    capabilities = ExecutionCapabilities(
        supported_environments={"ltx_25": frozenset({"windows"})},
        gpu_environments=frozenset(),
    )
    resolution = resolve_execution_environment(
        ExecutionRequestContext(engine="ltx_25", requires_gpu=True),
        ExecutionSettings(runtime_profile="hybrid_gpu"),
        capabilities,
    )

    assert resolution.blocked
    assert resolution.reason_code == "GPU_ENVIRONMENT_UNAVAILABLE"


def test_render_settings_preserve_old_files_and_round_trip_execution_preferences(tmp_path) -> None:
    config = tmp_path / "config"
    config.mkdir(parents=True)
    (config / "render_providers.json").write_text(
        json.dumps({"video": {"preference": "local_gpu"}}),
        encoding="utf-8",
    )
    store = RenderSettingsStore(tmp_path)

    legacy = store.get()
    updated = store.update(
        {
            "execution": {
                "runtime_profile": "hybrid_gpu",
                "model_environment_preferences": {
                    "hunyuan_video15": "wsl",
                    "ltx_25": "windows",
                },
            }
        }
    )

    assert legacy["execution"] == {
        "runtime_profile": "standard",
        "model_environment_preferences": {},
    }
    assert legacy["video"]["preference"] == "local_gpu"
    assert updated["execution"] == {
        "runtime_profile": "hybrid_gpu",
        "model_environment_preferences": {
            "hunyuan_video15": "wsl",
            "ltx_25": "windows",
        },
    }


def test_render_settings_sanitize_invalid_execution_values(tmp_path) -> None:
    store = RenderSettingsStore(tmp_path)
    updated = store.update(
        {
            "execution": {
                "runtime_profile": "unknown",
                "model_environment_preferences": {
                    "": "wsl",
                    "hunyuan_video15": "cpu",
                    "ltx_25": "wsl",
                },
            }
        }
    )

    assert updated["execution"] == {
        "runtime_profile": "standard",
        "model_environment_preferences": {"ltx_25": "wsl"},
    }
