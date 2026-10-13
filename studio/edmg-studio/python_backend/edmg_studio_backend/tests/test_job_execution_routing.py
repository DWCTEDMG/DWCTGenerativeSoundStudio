"""Exercise job admission without importing the application's runtime services."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("preference", ["auto", "external"])
@pytest.mark.parametrize("profile", ["standard", "external_linux"])
def test_linux_director_job_persists_native_execution(tmp_path, preference, profile):
    source = Path(__file__).parents[1] / "app.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_resolve_job_execution"
    )
    saved = []
    namespace = {
        "__package__": "edmg_studio_backend",
        "platform": SimpleNamespace(system=lambda: "Linux"),
        "render_settings": SimpleNamespace(get=lambda: {"execution": {"runtime_profile": profile}}),
        "store": SimpleNamespace(project_dir=lambda _: tmp_path),
        "jobs": SimpleNamespace(save=saved.append, publication_guard=lambda: None),
        "HUNYUAN_MODEL_ID": "hunyuan",
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    job = SimpleNamespace(
        type="qwen_director", project_id="project", id="director", attempt=1,
        payload={"execution_preference": {"environment": preference}},
    )
    namespace["_resolve_job_execution"](job)
    assert saved == [job]
    assert job.execution["requested_environment"] == preference
    assert job.execution["resolved_environment"] == "external"
    assert job.execution["worker_runtime"] == "linux-native"
    assert job.execution["resolution_reason"] == "BACKEND_NATIVE_EXECUTION"
