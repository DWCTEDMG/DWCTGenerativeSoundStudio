from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from edmg_studio_backend.api.routers import create_project_router
from edmg_studio_backend.contracts import CONTRACT_MODELS
from edmg_studio_backend.contracts.v1 import DirectorSceneContract
from edmg_studio_backend.render_profiles import (
    ACCEPTED_RENDER_SNAPSHOT_DIGEST_KEY,
    ACCEPTED_RENDER_SNAPSHOT_KEY,
    ProjectRenderProfile,
    accept_render_payload,
    render_snapshot_digest,
)
from edmg_studio_backend.store.projects import ProjectStore


FIXTURE = Path(__file__).parents[4] / "contracts" / "fixtures" / "v1" / "shared-contract-golden.json"


def fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_shared_fixture_matches_python_contract_vocabulary_and_preserves_extensions() -> None:
    golden = fixture()
    assert golden["contract_schema_version"] == "1.0"
    assert list(CONTRACT_MODELS) == golden["contract_types"]
    scene = DirectorSceneContract.model_validate(golden["director_scene"])
    assert scene.model_dump(mode="json", exclude_unset=True) == golden["director_scene"]


@pytest.mark.parametrize("sample", fixture()["exact_samples"]["valid"])
def test_shared_exact_sample_valid_cases(sample: str) -> None:
    start = sample if sample != "9223372036854775807" else "9223372036854775806"
    end = "1" if sample == "0" else "9223372036854775807"
    scene = DirectorSceneContract(scene_id="sample", start_sample=start, end_sample=end, intent="Exact")
    assert scene.start_sample == start


@pytest.mark.parametrize("sample", fixture()["exact_samples"]["invalid"])
def test_shared_exact_sample_invalid_cases(sample: str) -> None:
    with pytest.raises(ValidationError):
        DirectorSceneContract(scene_id="sample", start_sample=sample, end_sample="9223372036854775807", intent="Exact")


def test_render_profile_snapshot_digest_is_stable_and_excludes_reserved_keys() -> None:
    profile = ProjectRenderProfile(
        shared={"quality": "quality", "width": 1920, "height": 1080, "fps": 30, "renderer_id": "diffusion"},
        renderer_options={"diffusion": {"sampler": "euler", "future_option": True}},
    )
    first = accept_render_payload({"prompt": "neon", "seed": 7}, render_profile=profile)
    second = accept_render_payload({"seed": 7, "prompt": "neon"}, render_profile=profile.model_dump(mode="json"))
    assert first[ACCEPTED_RENDER_SNAPSHOT_DIGEST_KEY] == second[ACCEPTED_RENDER_SNAPSHOT_DIGEST_KEY]
    assert first[ACCEPTED_RENDER_SNAPSHOT_DIGEST_KEY] == render_snapshot_digest(first[ACCEPTED_RENDER_SNAPSHOT_KEY])
    assert ACCEPTED_RENDER_SNAPSHOT_KEY not in first[ACCEPTED_RENDER_SNAPSHOT_KEY]["payload"]
    assert first[ACCEPTED_RENDER_SNAPSHOT_KEY]["render_profile"]["renderer_options"]["diffusion"]["future_option"] is True


def test_project_render_profile_routes_round_trip_and_enforce_revision(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.create("Profile")
    app = FastAPI()
    app.include_router(create_project_router(
        get_store=lambda: store,
        project_response=lambda value: {"project": value.__dict__},
        assess_health=lambda *args: {},
    ))
    route = f"/v1/projects/{project.id}/render-profile"
    profile = ProjectRenderProfile(
        shared={"quality": "ultra", "width": 3840, "height": 2160, "fps": 60, "renderer_id": "ltx_25"},
        renderer_options={"ltx_25": {"steps": 12}},
        extensions={"vendor.example": {"preserve": True}},
    ).model_dump(mode="json")

    with TestClient(app) as client:
        legacy = client.get(route)
        assert legacy.status_code == 200
        assert legacy.json()["profile"] is None
        saved = client.put(route, json={"expected_revision": project.revision, "profile": profile})
        assert saved.status_code == 200, saved.text
        assert saved.json()["revision"] == project.revision + 1
        assert client.get(route).json()["profile"] == profile
        stale = client.put(route, json={"expected_revision": project.revision, "profile": profile})
        assert stale.status_code == 409
        invalid = client.put(route, json={"expected_revision": project.revision + 1, "profile": {"shared": {"fps": 0}}})
        assert invalid.status_code == 422
