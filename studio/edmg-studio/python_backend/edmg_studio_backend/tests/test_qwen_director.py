import json
import sys
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace

import pytest

from edmg_studio_backend.domain.director_scene import DirectorDocument
from edmg_studio_backend.errors import UserFacingError
from edmg_studio_backend.services import qwen_director
from edmg_studio_backend.services.model_load_coordinator import ModelLoadCanceled
from edmg_studio_backend.services.qwen_director import planning_messages, validate_proposal


def document():
    return DirectorDocument.model_validate(
        {
            "scenes": [
                {
                    "scene_id": "one",
                    "start_sample": "9007199254740993",
                    "end_sample": "9007199254788993",
                    "intent": "Walk through the forest",
                    "subjects": [{"id": "traveler", "appearance_notes": ["red coat"]}],
                }
            ]
        }
    )


def test_valid_proposal_is_a_draft_and_does_not_mutate_source():
    original = document()
    proposal = original.model_copy(deep=True)
    proposal.scenes[0].actions = ["walks across the stream"]
    accepted = validate_proposal(proposal.model_dump_json(), original)
    assert accepted.scenes[0].actions == ["walks across the stream"]
    assert original.scenes[0].actions == []
    assert "9007199254740993" in planning_messages(original, "Add motion")[1]["content"][0]["text"]


def test_compact_scene_updates_preserve_authoritative_document_fields():
    original = document()
    original.scenes[0].renderer_hints = {"source_scene": {"large": "metadata"}, "locked": False}
    update = {
        "scenes": [{
            "scene_id": "one",
            "actions": ["walks across the stream"],
            "camera": {"movement": "slow push-in"},
            "environment": {"secondary_motion": ["leaves drift"]},
        }]
    }

    accepted = validate_proposal(json.dumps(update), original)

    assert accepted.scenes[0].actions == ["walks across the stream"]
    assert accepted.scenes[0].camera.movement == "slow push-in"
    assert accepted.scenes[0].environment.secondary_motion == ["leaves drift"]
    assert accepted.scenes[0].start_sample == "9007199254740993"
    assert accepted.scenes[0].subjects == original.scenes[0].subjects
    assert accepted.scenes[0].renderer_hints == original.scenes[0].renderer_hints


def test_single_scene_window_binds_sole_update_to_authoritative_id():
    original = document()
    update = {
        "scenes": [{
            "scene_id": "Scene 1",
            "actions": ["walks beneath rotating constellations"],
        }]
    }

    accepted = validate_proposal(json.dumps(update), original)

    assert accepted.scenes[0].scene_id == "one"
    assert accepted.scenes[0].actions == ["walks beneath rotating constellations"]


def test_multi_scene_window_rejects_changed_scene_ids():
    original = document()
    second = original.scenes[0].model_copy(deep=True)
    second.scene_id = "two"
    second.start_sample = original.scenes[0].end_sample
    second.end_sample = str(int(second.start_sample) + 48000)
    original.scenes.append(second)
    update = {
        "scenes": [
            {"scene_id": "Scene 1", "actions": ["first"]},
            {"scene_id": "Scene 2", "actions": ["second"]},
        ]
    }

    with pytest.raises(ValueError, match="changed the scene set"):
        validate_proposal(json.dumps(update), original)


def test_multi_scene_window_rejects_partial_or_incomplete_scene_sets():
    original = document()
    second = original.scenes[0].model_copy(deep=True)
    second.scene_id = "two"
    second.start_sample = original.scenes[0].end_sample
    second.end_sample = str(int(second.start_sample) + 48000)
    original.scenes.append(second)

    with pytest.raises(ValueError, match="changed the scene set"):
        validate_proposal(json.dumps({"scenes": [{"scene_id": "one"}]}), original)
    with pytest.raises(ValueError, match="changed the scene set"):
        validate_proposal(
            json.dumps({"scenes": [{"scene_id": "one"}, {"scene_id": "Scene 2"}]}),
            original,
        )


def test_planning_messages_exclude_renderer_source_metadata():
    original = document()
    original.scenes[0].renderer_hints = {"source_scene": {"large": "metadata"}, "locked": False}

    prompt = planning_messages(original, "Add motion")[1]["content"][0]["text"]

    assert "9007199254740993" in prompt
    assert "source_scene" not in prompt
    assert '"locked":false' in prompt


def test_planning_messages_include_captured_timeline_context_compactly():
    context = {
        "version": 1,
        "selected_range": {"start_sample": "10", "end_sample": "20"},
        "markers": [{"id": "chorus"}],
        "clips": [{"clip_id": "vocal", "active_take_id": "take-2"}],
    }
    prompt = planning_messages(document(), "Add motion", context)[1]["content"][0]["text"]
    assert '"active_take_id":"take-2"' in prompt
    assert '"start_sample":"10"' in prompt


def test_long_scene_intent_is_preserved_and_documents_are_windowed():
    source = document()
    source.scenes[0].intent = "cosmic motion " * 900
    template = source.scenes[0].model_dump(mode="json")
    source.scenes = [
        type(source.scenes[0]).model_validate({
            **template,
            "scene_id": f"scene-{index}",
            "start_sample": str(index * 1000),
            "end_sample": str((index + 1) * 1000),
        })
        for index in range(13)
    ]

    prompt = planning_messages(source.model_copy(update={"scenes": source.scenes[:1]}), "Keep every detail")[1]["content"][0]["text"]
    windows = qwen_director._scene_windows(source)

    assert source.scenes[0].intent in prompt
    assert [len(window.scenes) for window in windows] == [1] * 13
    assert [scene.scene_id for window in windows for scene in window.scenes] == [scene.scene_id for scene in source.scenes]


def test_short_scenes_are_also_generated_in_independent_windows():
    source = document()
    template = source.scenes[0].model_dump(mode="json")
    source.scenes = [
        type(source.scenes[0]).model_validate({
            **template,
            "scene_id": f"scene-{index}",
            "start_sample": str(index * 1000),
            "end_sample": str((index + 1) * 1000),
            "intent": "brief motion",
        })
        for index in range(3)
    ]

    windows = qwen_director._scene_windows(source)

    assert [len(window.scenes) for window in windows] == [1, 1, 1]
    assert [window.scenes[0].scene_id for window in windows] == ["scene-0", "scene-1", "scene-2"]


@pytest.mark.parametrize("change", ["timing", "bible", "identity", "analysis", "scene_set"])
def test_model_cannot_override_approved_project_constraints(change):
    original = document()
    proposal = original.model_copy(deep=True)
    if change == "timing":
        proposal.scenes[0].end_sample = "9007199254788994"
    if change == "bible":
        proposal.story_bible.visual_style = "different"
    if change == "identity":
        proposal.scenes[0].subjects[0].appearance_notes = ["blue coat"]
    if change == "analysis":
        proposal.analysis_revision = 2
    if change == "scene_set":
        proposal.scenes = []
    with pytest.raises(ValueError):
        validate_proposal(proposal.model_dump_json(), original)


def _fake_runtime(
    monkeypatch, source, *, cancel_during_generate=False, generate_oom=False, oom_attempts=None,
    decoded_outputs=None,
):
    canceled = [False]
    calls = []
    remaining_ooms = [2 if generate_oom else 0 if oom_attempts is None else oom_attempts]
    cache_releases = []
    outputs = list(decoded_outputs or [source.model_dump_json()])

    class OutOfMemoryError(RuntimeError):
        pass

    class Inputs(dict):
        input_ids = [[1, 2, 3]]

        def to(self, _device):
            return self

    class Model:
        device = "cpu"
        hf_device_map = {"model.embed_tokens": 0, "model.layers.0": 1}

        @classmethod
        def from_pretrained(cls, _path, **kwargs):
            calls.append(("model", kwargs))
            return cls()

        def generate(self, **kwargs):
            calls.append(("generate", kwargs))
            canceled[0] = cancel_during_generate
            if cancel_during_generate:
                assert kwargs["stopping_criteria"][0](None, None) is True
            if remaining_ooms[0]:
                remaining_ooms[0] -= 1
                raise OutOfMemoryError("CUDA out of memory on device 0 requesting 4 GiB")
            return [[1, 2, 3, 4, 5]]

    class Processor:
        @classmethod
        def from_pretrained(cls, _path, **kwargs):
            calls.append(("processor", kwargs))
            return cls()

        def apply_chat_template(self, *_args, **kwargs):
            calls.append(("template", kwargs))
            return Inputs(input_ids=[[1, 2, 3]], token_type_ids=[0])

        def batch_decode(self, tokens, **_kwargs):
            assert tokens == [[4, 5]]
            calls.append(("decode", {}))
            return [outputs.pop(0)]

    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        __version__="fixture", AutoProcessor=Processor, Qwen3VLForConditionalGeneration=Model,
        StoppingCriteria=object, StoppingCriteriaList=list,
    ))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        __version__="fixture", inference_mode=nullcontext, OutOfMemoryError=OutOfMemoryError,
        cuda=SimpleNamespace(
            is_available=lambda: generate_oom or oom_attempts is not None,
            empty_cache=lambda: cache_releases.append(True),
        ),
    ))
    return canceled, calls, cache_releases


def test_director_reports_stages_and_loads_only_local_weights(tmp_path, monkeypatch):
    source = document()
    (tmp_path / "config.json").write_text('{"model_type":"qwen3_vl"}', encoding="utf-8")
    canceled, calls, _oom_type = _fake_runtime(monkeypatch, source)
    stages = []
    result = qwen_director.generate_proposal(
        tmp_path, source, "Add motion", max_memory={"cpu": 1024},
        cancel_check=lambda: canceled[0], progress_fn=lambda stage, _message: stages.append(stage),
    )
    assert result["status"] == "draft"
    assert result["document"] == source.model_dump(mode="json")
    assert stages == ["loading_model", "generating", "validating_draft"]
    loads = [kwargs for name, kwargs in calls if name in ("model", "processor")]
    assert all(kwargs["local_files_only"] and not kwargs["trust_remote_code"] for kwargs in loads)
    model_load = next(kwargs for name, kwargs in calls if name == "model")
    assert model_load["device_map"] == "balanced_low_0"
    assert next(kwargs for name, kwargs in calls if name == "template")["enable_thinking"] is False
    assert result["provenance"]["hf_device_map"]["model.layers.0"] == 1
    assert result["provenance"]["max_memory"] == {"cpu": 1024}


def test_token_cancellation_discards_partial_director_output(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text('{"model_type":"qwen3_vl"}', encoding="utf-8")
    canceled, calls, _oom_type = _fake_runtime(monkeypatch, document(), cancel_during_generate=True)
    with pytest.raises(ModelLoadCanceled):
        qwen_director.generate_proposal(
            tmp_path, document(), "Add motion", max_memory={"cpu": 1024},
            cancel_check=lambda: canceled[0],
        )
    assert "decode" not in [name for name, _kwargs in calls]


def test_generation_oom_retries_without_cache_and_preserves_request(tmp_path, monkeypatch):
    source = document()
    (tmp_path / "config.json").write_text('{"model_type":"qwen3_vl"}', encoding="utf-8")
    _canceled, calls, cache_releases = _fake_runtime(monkeypatch, source, oom_attempts=1)

    result = qwen_director.generate_proposal(
        tmp_path, source, "Keep every creative detail", max_memory={0: 1024}, max_new_tokens=1234,
    )

    generations = [kwargs for name, kwargs in calls if name == "generate"]
    assert result["status"] == "draft"
    assert len(generations) == 2
    assert generations[0]["max_new_tokens"] == generations[1]["max_new_tokens"] == 1234
    assert "use_cache" not in generations[0]
    assert generations[1]["use_cache"] is False
    assert cache_releases == [True]


def test_json_syntax_failure_gets_one_bounded_repair_pass(tmp_path, monkeypatch):
    source = document()
    repaired = source.model_copy(deep=True)
    repaired.scenes[0].actions = ["walks beneath rotating constellations"]
    (tmp_path / "config.json").write_text('{"model_type":"qwen3_vl"}', encoding="utf-8")
    _canceled, calls, _cache_releases = _fake_runtime(
        monkeypatch,
        source,
        decoded_outputs=['{"scenes":[{"scene_id":"one" "actions":[]}]}' , repaired.model_dump_json()],
    )
    stages = []

    result = qwen_director.generate_proposal(
        tmp_path,
        source,
        "Keep every creative detail",
        max_memory={0: 1024},
        progress_fn=lambda stage, _message: stages.append(stage),
    )

    assert result["document"]["scenes"][0]["actions"] == ["walks beneath rotating constellations"]
    assert len([kwargs for name, kwargs in calls if name == "generate"]) == 2
    templates = [kwargs for name, kwargs in calls if name == "template"]
    assert len(templates) == 2
    assert all(template["enable_thinking"] is False for template in templates)
    assert stages == ["loading_model", "generating", "validating_draft", "repairing_draft"]


def test_semantic_validation_failure_does_not_trigger_repair(tmp_path, monkeypatch):
    source = document()
    changed = source.model_copy(deep=True)
    changed.scenes = []
    (tmp_path / "config.json").write_text('{"model_type":"qwen3_vl"}', encoding="utf-8")
    _canceled, calls, _cache_releases = _fake_runtime(
        monkeypatch, source, decoded_outputs=[changed.model_dump_json()],
    )

    with pytest.raises(UserFacingError) as error:
        qwen_director.generate_proposal(
            tmp_path, source, "Keep every creative detail", max_memory={0: 1024},
        )

    assert error.value.code == "DIRECTOR_OUTPUT_INVALID"
    assert len([kwargs for name, kwargs in calls if name == "generate"]) == 1


def test_generation_oom_is_reported_as_actionable_user_error(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text('{"model_type":"qwen3_vl"}', encoding="utf-8")
    _canceled, calls, cache_releases = _fake_runtime(monkeypatch, document(), generate_oom=True)

    with pytest.raises(UserFacingError) as error:
        qwen_director.generate_proposal(
            tmp_path, document(), "Add motion", max_memory={0: 1024},
        )

    assert error.value.code == "DIRECTOR_MEMORY_EXHAUSTED"
    assert error.value.status_code == 422
    assert "GGUF" in error.value.hint
    assert "device 0 requesting 4 GiB" in error.value.hint
    assert len([call for call in calls if call[0] == "generate"]) == 2
    assert cache_releases == [True]


def test_dense_gpu_budgets_force_weights_across_all_selected_devices():
    gib = 1024**3
    budgets = qwen_director._dense_gpu_budgets({0: 46 * gib, 1: 46 * gib, 2: 46 * gib}, 17 * gib)

    assert set(budgets) == {0, 1, 2}
    assert all(7 * gib < budget < 8 * gib for budget in budgets.values())
    assert sum(sorted(budgets.values(), reverse=True)[:2]) < 17 * gib
    assert sum(budgets.values()) > 17 * gib


def test_director_default_token_limit_scales_by_scene_and_preserves_override():
    assert qwen_director._director_token_limit(1) == 1024
    assert qwen_director._director_token_limit(12) == 4096
    assert qwen_director._director_token_limit(30) == 4096
    assert qwen_director._director_token_limit(12, 8192) == 8192


def test_invalid_and_truncated_outputs_are_actionable_user_errors():
    with pytest.raises(UserFacingError) as invalid:
        qwen_director._validated_window_output("not json", document())
    assert invalid.value.code == "DIRECTOR_OUTPUT_INVALID"
    assert "Expecting value" in invalid.value.hint

    with pytest.raises(UserFacingError) as truncated:
        qwen_director._validated_window_output(
            '{"scenes":[', document(), generated_tokens=4096, token_limit=4096,
        )
    assert truncated.value.code == "DIRECTOR_OUTPUT_TRUNCATED"


def test_director_attention_kernel_prefers_cudnn_when_available():
    entered = []

    @contextmanager
    def kernel_context(backend):
        entered.append(backend)
        yield

    sdp_backend = SimpleNamespace(CUDNN_ATTENTION="cudnn")
    torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: True),
        nn=SimpleNamespace(attention=SimpleNamespace(SDPBackend=sdp_backend, sdpa_kernel=kernel_context)),
        backends=SimpleNamespace(cuda=SimpleNamespace(cudnn_sdp_enabled=lambda: True)),
    )

    context, name = qwen_director._director_attention_kernel(torch)
    with context:
        pass

    assert name == "cudnn_attention"
    assert entered == ["cudnn"]


def test_director_attention_kernel_keeps_safe_fallback_without_cudnn():
    context, name = qwen_director._director_attention_kernel(
        SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
    )

    with context:
        pass

    assert name == "sdpa_auto"


def test_canceled_worker_skips_model_lookup_and_loading(monkeypatch):
    class Models:
        def installed_path(self, _model):
            pytest.fail("Canceled worker inspected weights")

    with pytest.raises(ModelLoadCanceled):
        qwen_director.run_director_job({}, Models(), cancel_check=lambda: True)


def test_gpu_selection_auto_uses_all_and_explicit_selection_is_strict():
    assert qwen_director._selected_cuda_devices("auto", 3) == [0, 1, 2]
    assert qwen_director._selected_cuda_devices("2,0", 3) == [2, 0]
    with pytest.raises(ValueError, match="duplicate"):
        qwen_director._selected_cuda_devices("0,0", 3)
    with pytest.raises(ValueError, match="does not expose"):
        qwen_director._selected_cuda_devices("3", 3)


def test_worker_uses_live_memory_before_loading_and_reports_rejection(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text('{"model_type":"qwen3_vl"}', encoding="utf-8")
    (tmp_path / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {"weight": "weights.safetensors"}}), encoding="utf-8",
    )
    (tmp_path / "weights.safetensors").write_bytes(b"boundary fixture only")
    _canceled, calls, _oom_type = _fake_runtime(monkeypatch, document())
    available = [20 * 1024**3]
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(
        virtual_memory=lambda: SimpleNamespace(available=available[0]),
    ))
    models = SimpleNamespace(installed_path=lambda _model: tmp_path)
    payload = {"model_id": "hf_qwen3_vl_8b_director", "document": document().model_dump(mode="json"),
               "instruction": "Add motion", "source_revision": 2}
    accepted = qwen_director.run_director_job(payload, models)
    assert accepted["source_revision"] == 2
    assert next(kwargs for name, kwargs in calls if name == "model")["max_memory"] == {"cpu": 16 * 1024**3}
    calls.clear()
    available[0] = 3 * 1024**3
    with pytest.raises(UserFacingError) as error:
        qwen_director.run_director_job(payload, models)
    assert error.value.code == "DIRECTOR_MEMORY_REJECTED"
    assert calls == []
