"""One policy-driven boundary for Windows and WSL execution workers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import ContextManager

from pydantic import JsonValue

from .contracts import ExecutionPreference, ExecutionResult, ResolvedExecutionEnvironment
from .policy import (
    ExecutionCapabilities,
    ExecutionRequestContext,
    ExecutionResolution,
    ExecutionSettings,
    resolve_execution_environment,
)
from .staging import (
    AdmittedExecutionResult,
    PreparedExecutionAttempt,
    admit_execution_result,
    prepare_execution_attempt,
)

ExecutionAdapter = Callable[["DispatchContext", PreparedExecutionAttempt], Path]


class ExecutionDispatchBlocked(RuntimeError):
    def __init__(self, resolution: ExecutionResolution):
        self.resolution = resolution
        super().__init__(resolution.reason_code)


@dataclass(frozen=True)
class DispatchContext:
    project_root: Path
    project_id: str
    job_id: str
    attempt: int
    engine: str
    publication_guard: Callable[..., ContextManager[bool]]
    preference: ExecutionPreference = field(default_factory=ExecutionPreference)
    requires_gpu: bool = True
    physical_gpu_device_ids: tuple[str, ...] = ()
    inputs: Mapping[str, Path] = field(default_factory=dict)
    parameters: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class DispatchedExecution:
    resolution: ExecutionResolution
    prepared: PreparedExecutionAttempt
    result: ExecutionResult
    admitted: AdmittedExecutionResult


class ExecutionDispatcher:
    def __init__(
        self,
        *,
        settings_provider: Callable[[], ExecutionSettings],
        capabilities_provider: Callable[[], ExecutionCapabilities],
        adapters: Mapping[ResolvedExecutionEnvironment, ExecutionAdapter],
    ) -> None:
        self._settings_provider = settings_provider
        self._capabilities_provider = capabilities_provider
        self._adapters = dict(adapters)

    def resolve(self, context: DispatchContext) -> ExecutionResolution:
        return resolve_execution_environment(
            ExecutionRequestContext(
                engine=context.engine,
                preference=context.preference,
                requires_gpu=context.requires_gpu,
            ),
            self._settings_provider(),
            self._capabilities_provider(),
        )

    def dispatch(self, context: DispatchContext) -> DispatchedExecution:
        resolution = self.resolve(context)
        environment = resolution.resolved_environment
        if resolution.blocked or environment is None or environment == "external":
            raise ExecutionDispatchBlocked(resolution)
        adapter = self._adapters.get(environment)
        if adapter is None:
            raise ExecutionDispatchBlocked(
                resolution.model_copy(update={"blocked": True, "reason_code": "EXECUTION_ADAPTER_UNAVAILABLE"})
            )
        prepared = prepare_execution_attempt(
            project_root=context.project_root,
            project_id=context.project_id,
            job_id=context.job_id,
            attempt=context.attempt,
            engine=context.engine,
            environment=environment,
            physical_gpu_device_ids=context.physical_gpu_device_ids,
            inputs=context.inputs,
            parameters=context.parameters,
        )
        result_path = adapter(context, prepared)
        admitted = admit_execution_result(
            prepared,
            result_path,
            publication_guard=context.publication_guard,
        )
        return DispatchedExecution(
            resolution=resolution,
            prepared=prepared,
            result=admitted.result,
            admitted=admitted,
        )
