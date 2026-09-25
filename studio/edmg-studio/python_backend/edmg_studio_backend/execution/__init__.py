"""Execution-plane contracts and orchestration primitives.

Only stable cross-module interfaces are exported here. Process transport,
policy, staging, and dispatch remain in focused sibling modules.
"""

from .contracts import (
    ExecutionEnvironment,
    ExecutionFailure,
    ExecutionFailureCode,
    ExecutionManifest,
    ExecutionPreference,
    ExecutionResult,
    ManifestArtifact,
    ResolvedExecutionEnvironment,
    ResultArtifact,
    RuntimeProfile,
    assert_result_matches_manifest,
)

__all__ = [
    "ExecutionEnvironment",
    "ExecutionFailure",
    "ExecutionFailureCode",
    "ExecutionManifest",
    "ExecutionPreference",
    "ExecutionResult",
    "ManifestArtifact",
    "ResolvedExecutionEnvironment",
    "ResultArtifact",
    "RuntimeProfile",
    "assert_result_matches_manifest",
]
