import json
import sys
from contextlib import nullcontext
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


def _fake_runtime(monkeypatch, source, *, cancel_during_generate=False, generate_oom=False):
    canceled = [False]
    calls = []

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
            if generate_oom:
                raise OutOfMemoryError("CUDA out of memory")
            return [[1, 2, 3, 4, 5]]

    class Processor:
        @classmethod
        def from_pretrained(cls, _path, **kwargs):
            calls.append(("processor", kwargs))
            return cls()

        def apply_chat_template(self, *_args, **_kwargs):
            return Inputs(input_ids=[[1, 2, 3]], token_type_ids=[0])

        def batch_decode(self, tokens, **_kwargs):
            assert tokens == [[4, 5]]
            calls.append(("decode", {}))
            return [source.model_dump_json()]

    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        __version__="fixture", AutoProcessor=Processor, Qwen3VLForConditionalGeneration=Model,
        StoppingCriteria=object, StoppingCriteriaList=list,
    ))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        __version__="fixture", inference_mode=nullcontext, OutOfMemoryError=OutOfMemoryError,
        cuda=SimpleNamespace(is_available=lambda: False),
    ))
    return canceled, calls, OutOfMemoryError


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


def test_generation_oom_is_reported_as_actionable_user_error(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text('{"model_type":"qwen3_vl"}', encoding="utf-8")
    _canceled, _calls, _oom_type = _fake_runtime(monkeypatch, document(), generate_oom=True)

    with pytest.raises(UserFacingError) as error:
        qwen_director.generate_proposal(
            tmp_path, document(), "Add motion", max_memory={"cpu": 1024},
        )

    assert error.value.code == "DIRECTOR_MEMORY_EXHAUSTED"
    assert error.value.status_code == 422
    assert "smaller or GGUF" in error.value.hint


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
