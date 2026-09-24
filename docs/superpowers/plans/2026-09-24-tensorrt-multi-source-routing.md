# TensorRT Multi-Source Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend EDMG Studio's existing TensorRT component runtime to route supported ONNX, PyTorch checkpoint, Hugging Face safetensors, and prebuilt engine sources truthfully while keeping GGUF on llama.cpp.

**Architecture:** Add source classification and route resolution to the current component adapter registry, then pass normalized descriptors through the existing runtime service, isolated worker, builders, cache, validation, and policy-aware managers. Extend current API payloads and WinUI contracts/presentation so recognition, build eligibility, validation, fallback, and actual acceleration remain separate observable states.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, PyTorch, optional Torch-TensorRT, TensorRT, pytest, C#/.NET 8, WinUI 3, MSTest.

**Spec:** `docs/superpowers/specs/2026-09-24-tensorrt-multi-source-routing-design.md`

## Global Constraints

- Preserve all existing render routes, request defaults, cache compatibility, and user-owned uncommitted work.
- Keep native TensorRT and compiler imports inside the isolated backend worker; WinUI and the API process remain control/status surfaces.
- Reuse `ComponentAdapterRegistry`, `RuntimeManager`, `RuntimeProcess`, `EngineCache`, the model-load coordinator, render settings, resource policy, CUDA device selection, and current runtime jobs.
- Do not install, remove, or synchronize dependencies. Missing optional packages are capability results.
- Never infer model/operator support from a recognized extension alone.
- Global TensorRT disable wins over per-operation preferences.
- Never report TensorRT acceleration without a validated execution receipt.
- Do not stage or commit unrelated dirty files. Before every commit, inspect `git diff --cached --name-only`.

## Review Focus

- A directory containing both GGUF and safetensors must not be guessed; classification must use the admitted model record or return an ambiguity reason.
- A sharded safetensors index with a missing shard must be unsupported, with the missing file named in the reason.
- A prebuilt engine from an incompatible compute capability or TensorRT version must be quarantined, never published ready.
- A `.pt` file whose architecture has no registered loader must fall back or fail according to policy rather than attempting unsafe deserialization in the API process.
- An older runtime-status payload without new route fields must continue to deserialize in WinUI with neutral defaults.

---

## File Structure

- Create `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/sources.py`: side-effect-free source descriptors and deterministic classification.
- Create `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/routes.py`: route decision types, compiler discovery, and policy-neutral route selection.
- Create `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/torch_builder.py`: worker-only registered PyTorch/Hugging Face loading and Torch-TensorRT compilation.
- Create `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/prebuilt.py`: prebuilt engine metadata inspection, admission, validation, and cache publication.
- Modify `runtime/adapters.py`: declare admitted source kinds, architecture loaders, compiler routes, and component constraints.
- Modify `runtime/cache.py`: versioned multi-source identity compatibility and manifest metadata.
- Modify `runtime/worker.py`, `runtime/process.py`, and `runtime/service.py`: transport descriptors/routes through existing jobs and worker isolation.
- Modify existing component builders only to use shared identity fields; retain their execution logic.
- Modify `services/model_catalog.py` and `services/model_runtime_registry.py`: expose managed source descriptors without moving package ownership.
- Modify `api/runtime.py`: accept managed model/component selection and serialize route status through existing endpoints.
- Modify `runtime/manager.py` and existing render integration points only where required to record route/fallback/execution evidence.
- Modify `studio/edmg-studio-winui/src/EdmgStudio.Core/Models/StudioApiModels.cs`: compatible route/status JSON contracts.
- Modify `studio/edmg-studio-winui/Pages/ModelsPage.xaml(.cs)` and `Pages/SettingsPage.Runtime.cs`: display route, support, compiler availability, and reasons.
- Modify existing TensorRT documentation and blueprints to describe qualification states.

### Task 1: Deterministic model-source classification

**Files:**
- Create: `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/sources.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_component_runtime.py`

**Interfaces:**
- Produces: `SourceKind(str, Enum)`, `ModelSourceDescriptor`, and `classify_model_source(model_root: Path, *, model_id: str, model_family: str, component: str, admitted_format: str | None = None) -> ModelSourceDescriptor`.
- `ModelSourceDescriptor.identity_fields() -> dict[str, object]` returns only applicable non-null identity fields.

- [ ] **Step 1: Add failing classification tests**

Add tests that create minimal ONNX, `.pt`, `.pth`, HF `config.json` plus safetensors, sharded safetensors indexes, `.engine`, `.plan`, and GGUF fixtures. Assert exact `SourceKind`, evidence files, architecture, hashes, and unsupported reasons. Include ambiguity and missing-shard cases:

```python
def test_huggingface_safetensors_requires_config_and_complete_shards(tmp_path):
    root = tmp_path / "model"
    root.mkdir()
    (root / "config.json").write_text('{"architectures":["UNet2DConditionModel"]}')
    (root / "model.safetensors.index.json").write_text(
        '{"weight_map":{"a":"model-00001-of-00002.safetensors",'
        '"b":"model-00002-of-00002.safetensors"}}'
    )
    (root / "model-00001-of-00002.safetensors").write_bytes(b"one")

    result = classify_model_source(
        root, model_id="fixture", model_family="sd15", component="unet"
    )

    assert result.kind is SourceKind.UNKNOWN
    assert "model-00002-of-00002.safetensors" in result.reason
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run from `studio/edmg-studio/python_backend`:

```powershell
uv run --frozen --no-sync --group test python -m pytest edmg_studio_backend/tests/test_component_runtime.py -k "source or safetensors or gguf" -q
```

Expected: collection/import failure because `runtime.sources` does not exist.

- [ ] **Step 3: Implement source descriptors and classification**

Implement immutable dataclasses, canonical path handling, SHA-256 hashing via the existing cache helper, HF config/index parsing, complete-shard validation, admitted-format disambiguation, and explicit GGUF exclusion. Do not import Torch, TensorRT, Transformers, or safetensors.

- [ ] **Step 4: Run focused and full component-runtime tests**

Run the focused command, then:

```powershell
uv run --frozen --no-sync --group test python -m pytest edmg_studio_backend/tests/test_component_runtime.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit only Task 1 files**

```powershell
git add -- studio/edmg-studio/python_backend/edmg_studio_backend/runtime/sources.py studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_component_runtime.py
git diff --cached --name-only
git commit -m "Add deterministic TensorRT source classification"
```

### Task 2: Route resolution and adapter declarations

**Files:**
- Create: `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/routes.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/adapters.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/manager.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_component_runtime.py`

**Interfaces:**
- Consumes: `ModelSourceDescriptor` and `SourceKind` from Task 1.
- Produces: `CompilerAvailability`, `RuntimeRouteDecision`, `discover_compilers(import_spec=importlib.util.find_spec) -> CompilerAvailability`, and `resolve_runtime_route(descriptor, adapter, compilers) -> RuntimeRouteDecision`.
- `ComponentAdapter` gains `source_kinds`, `architectures`, `compiler_routes`, and optional `loader_id`.

- [ ] **Step 1: Add failing route tests**

Cover ONNX preservation, `.pt`/`.pth` Torch-TensorRT preference, declared `torch.compile` fallback, HF routing, prebuilt routing, missing compiler, unregistered architecture, and GGUF-to-llama.cpp:

```python
def test_gguf_route_is_llama_cpp_and_never_tensorrt(tmp_path):
    source = ModelSourceDescriptor(
        model_id="qwen", model_family="qwen", component="language_model",
        root=tmp_path, kind=SourceKind.GGUF, files=(), hashes={},
    )
    decision = resolve_runtime_route(source, ComponentAdapterRegistry().get("qwen", "language_model"), CompilerAvailability())
    assert decision.selected_runtime == "llama_cpp"
    assert decision.compiler is None
    assert decision.supported
```

- [ ] **Step 2: Verify route tests fail for missing APIs**

Run the route-focused pytest selection and confirm failure because `runtime.routes` and adapter declarations are absent.

- [ ] **Step 3: Implement route types, compiler discovery, and declarations**

Use module discovery without importing native packages in the API process. Resolve only routes explicitly declared by the selected component adapter. Update runtime plan/status fields without changing current selection behavior yet.

- [ ] **Step 4: Verify route and existing policy tests pass**

Run route-focused tests plus tests matching `policy`, `fallback`, `registry`, and `metadata` in `test_component_runtime.py`.

- [ ] **Step 5: Commit only Task 2 files**

Commit with message `Add TensorRT multi-source route resolution` after inspecting staged paths.

### Task 3: Multi-source cache identity and manifest compatibility

**Files:**
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/cache.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/builder.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/unet_builder.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_component_runtime.py`

**Interfaces:**
- Consumes: `ModelSourceDescriptor.identity_fields()` and `RuntimeRouteDecision`.
- Produces: `build_engine_identity(...) -> dict[str, object]` in `cache.py`; legacy callers of `engine_key(identity)` remain valid.

- [ ] **Step 1: Add failing cache-identity tests**

Assert key changes for source hash, HF config hash, route, compiler versions, precision, profile, and compute capability. Assert irrelevant null fields are omitted and a legacy identity still looks up its existing entry.

```python
def test_multi_source_identity_omits_irrelevant_fields_and_changes_with_compiler():
    first = build_engine_identity(source=source, route=route, precision="fp16", profile=profile,
                                  environment={"tensorrt":"10.15", "torch_tensorrt":"2.8"})
    second = build_engine_identity(source=source, route=route, precision="fp16", profile=profile,
                                   environment={"tensorrt":"10.15", "torch_tensorrt":"2.9"})
    assert "onnx" not in first
    assert engine_key(first) != engine_key(second)
```

- [ ] **Step 2: Verify identity tests fail for the missing helper**

Run the cache/identity pytest selection and confirm expected failure.

- [ ] **Step 3: Implement shared identity construction and adapt existing builders**

Preserve `SCHEMA = 1` reading for current entries. Introduce a versioned identity payload only where the new fields are present; do not invalidate existing ONNX entries unnecessarily. Store route/source metadata in manifests without changing atomic publication semantics.

- [ ] **Step 4: Run cache, corruption, memory-guard, builder, and component tests**

Run `test_component_runtime.py` completely and confirm all pass.

- [ ] **Step 5: Commit only Task 3 files**

Commit with message `Extend TensorRT cache identity for source routes`.

### Task 4: Torch-TensorRT and Hugging Face worker path

**Files:**
- Create: `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/torch_builder.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/worker.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/process.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/adapters.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_component_runtime.py`

**Interfaces:**
- Consumes: source descriptors, route decisions, shared cache identity, adapter `loader_id`, existing validation limits, device, precision, profiles, and workspace limits.
- Produces: `prepare_torch_component(...) -> tuple[TensorExecutor, dict, str]` matching existing adapter `prepare` results.
- Registered loaders return a PyTorch module plus representative named inputs; arbitrary pickle execution is never performed for an unregistered architecture.

- [ ] **Step 1: Add failing worker/compiler tests**

Use injectable fake loaders/compilers to verify `.pt` and HF loader selection, Torch-TensorRT preference, declared `torch.compile` backend selection, named inputs, compiler absence, unsupported operators, cancellation, device forwarding, and no native import in the API process.

```python
def test_torch_builder_reports_unsupported_operator_without_publishing(tmp_path, monkeypatch):
    compiler = FakeCompiler(error=RuntimeError("aten::fixture is unsupported"))
    with pytest.raises(RuntimeError, match="aten::fixture"):
        prepare_torch_component(..., compiler=compiler)
    assert EngineCache(tmp_path).entries() == []
```

- [ ] **Step 2: Verify tests fail because the Torch builder is absent**

Run tests matching `torch_builder`, `torch_tensorrt`, `torch_compile`, and `unsupported_operator`.

- [ ] **Step 3: Implement the registered worker-only Torch path**

Load optional packages only inside `prepare_torch_component`. Refuse unregistered loaders before `torch.load`. Use adapter-provided inputs and existing validation thresholds. Publish only after numerical validation and benchmark recording. Forward cancellation and memory limits through existing worker/process messages.

- [ ] **Step 4: Run focused tests and current worker transport tests**

Run the new tests plus selections matching `runtime_process`, `memory_guard`, `validation`, and `fallback`.

- [ ] **Step 5: Commit only Task 4 files**

Commit with message `Add worker-isolated Torch-TensorRT compilation`.

### Task 5: Prebuilt engine admission and validation

**Files:**
- Create: `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/prebuilt.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/worker.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/adapters.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_component_runtime.py`

**Interfaces:**
- Consumes: descriptor, component contract, device, precision, validation limits, shared identity, `EngineCache`, and existing `TensorExecutor` binding inspection.
- Produces: `admit_prebuilt_engine(...) -> tuple[TensorExecutor, dict, str]` with cache status `admitted` or `ready`; rejected candidates are quarantined with an exact reason.

- [ ] **Step 1: Add failing direct-engine tests**

Test `.engine` and `.plan`, compatible binding/profile admission, missing metadata, wrong component bindings, incompatible compute capability/TensorRT version, validation failure, quarantine, and the rule that deserialization alone is insufficient.

- [ ] **Step 2: Verify direct-engine tests fail**

Run tests matching `prebuilt`, `direct_engine`, and `plan`.

- [ ] **Step 3: Implement prebuilt inspection and admission**

Perform all TensorRT imports and deserialization in the worker. Require managed source identity and component metadata, inspect named bindings and optimization profiles, enforce resource/device constraints, run representative inference against the component validation contract, and atomically publish only passing engines.

- [ ] **Step 4: Run direct-engine, cache, and validation tests**

Confirm quarantined candidates cannot be returned by `lookup` and passing candidates retain `built=false`, `admitted_prebuilt=true` metadata.

- [ ] **Step 5: Commit only Task 5 files**

Commit with message `Validate and admit prebuilt TensorRT engines`.

### Task 6: Model catalog, runtime jobs, policy, and status serialization

**Files:**
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/services/model_catalog.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/services/model_runtime_registry.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/service.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/runtime/manager.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/api/runtime.py`
- Modify: relevant request/receipt integration in `studio/edmg-studio/python_backend/edmg_studio_backend/app.py` only if no smaller existing hook carries runtime metadata.
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_component_runtime.py`
- Modify: `studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_model_runtime_registry.py`

**Interfaces:**
- Consumes: classification, route decisions, builders/admission, cache entries, existing runtime policy and managed model records.
- Produces: existing `/v1/runtime/status`, `/v1/runtime/jobs`, preflight, and receipt payloads with optional `source_kind`, `architecture`, `requested_route`, `selected_route`, `compiler`, `compiler_available`, `route_supported`, `route_reason`, `fallback_runtime`, `validated`, and `accelerating` fields.
- `RuntimeJobRequest` gains optional managed `model_id`; server resolves paths from the catalog.

- [ ] **Step 1: Add failing service/API tests**

Cover managed-path resolution, arbitrary-path rejection, each route's serialization, missing compiler, unsupported architecture/operator, global disable, strict failure, allowed fallback, actual-acceleration receipt, and backward-compatible requests without `model_id`.

```python
def test_runtime_status_never_marks_recognized_but_unvalidated_route_accelerating(...):
    component = next(item for item in status["components"] if item["component"] == "unet")
    assert component["source_kind"] == "huggingface"
    assert component["route_supported"] is True
    assert component["validated"] is False
    assert component["accelerating"] is False
```

- [ ] **Step 2: Verify API/status tests fail on absent fields**

Run focused component-runtime and model-registry tests and confirm expected assertion failures.

- [ ] **Step 3: Implement catalog-to-route flow and truthful status**

Resolve sources only from managed records, merge route evidence into current component status, pass normalized descriptors into existing jobs, and keep fallback history observable. Set `accelerating` only from execution metadata, never from support or ready cache state.

- [ ] **Step 4: Run focused backend suites**

Run complete `test_component_runtime.py`, `test_model_runtime_registry.py`, and affected render/preflight tests discovered with `rg "runtime_components|runtime_metadata|tensorrt" edmg_studio_backend/tests`.

- [ ] **Step 5: Commit only Task 6 files**

Commit with message `Expose truthful TensorRT source route status`.

### Task 7: WinUI contracts and user-visible route status

**Files:**
- Modify: `studio/edmg-studio-winui/src/EdmgStudio.Core/Models/StudioApiModels.cs`
- Modify: `studio/edmg-studio-winui/tests/EdmgStudio.Core.Tests/StudioApiClientTests.cs`
- Create or modify: `studio/edmg-studio-winui/src/EdmgStudio.Core/Models/RenderRuntimeCapabilities.cs`
- Modify: `studio/edmg-studio-winui/tests/EdmgStudio.Core.Tests/RenderRuntimeCapabilitiesTests.cs`
- Modify carefully around concurrent work: `studio/edmg-studio-winui/Pages/ModelsPage.xaml`
- Modify carefully around concurrent work: `studio/edmg-studio-winui/Pages/ModelsPage.xaml.cs`
- Modify: `studio/edmg-studio-winui/Pages/SettingsPage.Runtime.cs`

**Interfaces:**
- Consumes: optional backend route/status fields from Task 6.
- Produces: nullable/defaulted C# properties and a pure presentation helper `TensorRtRoutePresentation.From(RuntimeComponentStatus) -> TensorRtRoutePresentation` with label, state, detail, and severity.

- [ ] **Step 1: Add failing C# serialization and presentation tests**

Extend the API fixture with HF/Torch-TensorRT, prebuilt, GGUF, unsupported, and fallback entries. Add an old-payload test without new fields. Assert labels and that recognized/unvalidated/fallback entries never say accelerated.

```csharp
[TestMethod]
public void TensorRtRoutePresentation_DoesNotCallUnvalidatedRouteAccelerated()
{
    var status = new RuntimeComponentStatus { SourceKind = "huggingface", SelectedRoute = "huggingface_torch_tensorrt", RouteSupported = true, Validated = false, Accelerating = false };
    TensorRtRoutePresentation view = TensorRtRoutePresentation.From(status);
    Assert.AreEqual("Hugging Face via Torch-TensorRT", view.RouteLabel);
    StringAssert.DoesNotContain(view.State, "Accelerated");
}
```

- [ ] **Step 2: Run WinUI Core tests and verify RED**

```powershell
dotnet test studio/edmg-studio-winui/tests/EdmgStudio.Core.Tests/EdmgStudio.Core.Tests.csproj --no-restore --filter "StudioApiClientTests|RenderRuntimeCapabilitiesTests"
```

Expected: compilation failure for missing properties/helper.

- [ ] **Step 3: Implement compatible contracts and pure presentation helper**

Use optional/default properties so old payloads deserialize. Keep route wording in the Core helper rather than code-behind.

- [ ] **Step 4: Update Models and Settings UI without overwriting dirty work**

Re-read current diffs immediately before editing. Add route, compiler, support/validation, and reason text to existing runtime panels. Do not alter the concurrent Qwen multi-GPU controls or initialization guards. WinUI never performs route selection itself.

- [ ] **Step 5: Run focused Core tests and compile the WinUI project**

Run the filtered Core tests, then:

```powershell
dotnet build studio/edmg-studio-winui/EdmgStudio.WinUI.slnx -c Release -p:Platform=x64 --no-restore
```

- [ ] **Step 6: Commit only Task 7 files**

Inspect the full unstaged diff to separate concurrent edits; use patch staging if a file contains both owners' changes. Commit with message `Show TensorRT source routes in WinUI`.

### Task 8: Documentation and full verification

**Files:**
- Modify: `docs/TENSORRT_RUNTIME_INTEGRATION.md`
- Modify: `EDMG_TensorRT_Full_Studio_Wide_Blueprint.md`
- Modify: `studio/edmg-studio-winui/EDMG_TensorRT_Full_Studio_Wide_Blueprint.md`
- Modify: `studio/edmg-studio-winui/README.md`
- Modify: `STUDIO_PROGRESS.md` only in the currently authorized ownership section and only after re-reading concurrent updates.

**Interfaces:**
- Consumes: implemented routes and fresh verification evidence.
- Produces: documented qualification matrix separating implemented, dependency-available, validated, execution-proven, and external-blocker states.

- [ ] **Step 1: Update documentation with exact implemented states**

Document ONNX, PyTorch/Torch-TensorRT, HF safetensors, prebuilt engines, GGUF exclusion, strict/fallback behavior, cache identity, optional dependency state, and the difference between tests/builds and live execution.

- [ ] **Step 2: Run backend diff and syntax checks**

```powershell
git diff --check
uv run --project studio/edmg-studio/python_backend --frozen --no-sync --group test python -m compileall -q studio/edmg-studio/python_backend/edmg_studio_backend
```

- [ ] **Step 3: Run the frozen aggregate backend suites**

From the repository root:

```powershell
uv run --project studio/edmg-studio/python_backend --frozen --no-sync --group test python scripts/run_pytest_scopes.py
```

Record both repository and backend counts, failures/skips, command, exit code, timestamp, commit, and dirty state. Do not synchronize dependencies.

- [ ] **Step 4: Run WinUI Core and Release build verification**

```powershell
dotnet test studio/edmg-studio-winui/tests/EdmgStudio.Core.Tests/EdmgStudio.Core.Tests.csproj --no-restore
dotnet build studio/edmg-studio-winui/EdmgStudio.WinUI.slnx -c Release -p:Platform=x64 --no-restore
```

Record test count and build warnings/errors separately.

- [ ] **Step 5: Probe optional runtime availability without changing dependencies**

Use the pinned backend interpreter to report Python, Torch, CUDA, TensorRT, Torch-TensorRT module discovery, and available `torch.compile` backends. If Torch-TensorRT is absent or real-model/operator execution is unavailable, record it as an external live-qualification blocker rather than weakening tests or installing packages.

- [ ] **Step 6: Review every requirement against the spec**

Confirm routing, detection, direct loading, fallback truthfulness, cache identity, memory/device policy, jobs/APIs, UI serialization/presentation, docs, and verification. List any unimplemented item explicitly.

- [ ] **Step 7: Commit only documentation and intentional implementation files still uncommitted**

Inspect staged paths, preserve concurrent changes, and commit with message `Document TensorRT multi-source qualification`.

- [ ] **Step 8: Report final evidence without overstating qualification**

Report files changed, commits, exact backend/.NET/build results, installed optional dependency state, and any external blocker. Keep live GPU inference, packaged execution, and visible UI verification distinct from automated tests and compilation.
