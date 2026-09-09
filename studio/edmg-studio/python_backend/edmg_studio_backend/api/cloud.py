from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter

from ..schemas import (
    CloudAwsBundleRequest,
    CloudAwsTestRequest,
    CloudAzureTestRequest,
    CloudHfBucketSettingsRequest,
    CloudHfBucketTestRequest,
    CloudLightningBundleRequest,
)


@dataclass(frozen=True)
class CloudRouterDependencies:
    aws_test: Callable[[CloudAwsTestRequest], Any]
    aws_bundle: Callable[[CloudAwsBundleRequest], Any]
    azure_test: Callable[[CloudAzureTestRequest], Any]
    hf_status: Callable[[], Any]
    hf_test: Callable[[CloudHfBucketTestRequest], Any]
    hf_settings_get: Callable[[], Any]
    hf_settings_set: Callable[[CloudHfBucketSettingsRequest], Any]
    lightning_bundle: Callable[[CloudLightningBundleRequest], Any]


def create_cloud_router(deps: CloudRouterDependencies) -> APIRouter:
    router = APIRouter()

    @router.post("/v1/cloud/aws/test")
    def cloud_aws_test(req: CloudAwsTestRequest): return deps.aws_test(req)

    @router.post("/v1/cloud/aws/bundle")
    def cloud_aws_bundle(req: CloudAwsBundleRequest): return deps.aws_bundle(req)

    @router.post("/v1/cloud/azure/test")
    def cloud_azure_test(req: CloudAzureTestRequest): return deps.azure_test(req)

    @router.get("/v1/cloud/hf/status")
    def cloud_hf_status(): return deps.hf_status()

    @router.post("/v1/cloud/hf/test")
    def cloud_hf_test(req: CloudHfBucketTestRequest): return deps.hf_test(req)

    @router.get("/v1/cloud/hf/settings")
    def cloud_hf_settings_get(): return deps.hf_settings_get()

    @router.post("/v1/cloud/hf/settings")
    def cloud_hf_settings_set(req: CloudHfBucketSettingsRequest): return deps.hf_settings_set(req)

    @router.post("/v1/cloud/lightning/bundle")
    def cloud_lightning_bundle(req: CloudLightningBundleRequest): return deps.lightning_bundle(req)

    return router
