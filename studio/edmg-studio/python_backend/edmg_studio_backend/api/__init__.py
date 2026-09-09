"""Extracted FastAPI routers for Studio backend domains."""

from .cloud import CloudRouterDependencies, create_cloud_router
from .jobs import JobRouterDependencies, create_jobs_router
from .project_codex import ProjectCodexDependencies, create_project_codex_router
from .project_intelligence import (
    ProjectIntelligenceDependencies,
    create_project_intelligence_router,
)
from .project_media import ProjectMediaDependencies, create_project_media_router
from .project_outputs import ProjectOutputDependencies, create_project_output_router
from .project_workbench import ProjectWorkbenchDependencies, create_project_workbench_router
from .providers import ProviderRouterDependencies, create_provider_router
from .render import RenderRouterDependencies, create_render_router
from .routers import create_models_router, create_project_router, create_system_router
from .setup import SetupRouterDependencies, create_setup_router
from .system_settings import SystemSettingsDependencies, create_system_settings_router

__all__ = [
    "JobRouterDependencies",
    "CloudRouterDependencies",
    "ProviderRouterDependencies",
    "RenderRouterDependencies",
    "ProjectCodexDependencies",
    "ProjectIntelligenceDependencies",
    "ProjectMediaDependencies",
    "ProjectOutputDependencies",
    "ProjectWorkbenchDependencies",
    "SystemSettingsDependencies",
    "SetupRouterDependencies",
    "create_jobs_router",
    "create_cloud_router",
    "create_models_router",
    "create_project_router",
    "create_provider_router",
    "create_render_router",
    "create_project_codex_router",
    "create_project_intelligence_router",
    "create_project_media_router",
    "create_project_output_router",
    "create_project_workbench_router",
    "create_system_router",
    "create_system_settings_router",
    "create_setup_router",
]
