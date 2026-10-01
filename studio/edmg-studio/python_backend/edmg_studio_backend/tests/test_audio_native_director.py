from __future__ import annotations

import pytest

from edmg_studio_backend.domain.director_scene import (
    Camera,
    DirectorDocument,
    Environment,
    SceneSpec,
)
from edmg_studio_backend.services.audio_native_director import (
    FALLBACK_AUDIO_NATIVE_MODEL_ID,
    _automatic_long_audio_model,
    _automatic_oom_fallback_model,
    _compact_prompt_evidence,
    _long_audio_max_memory,
    _long_audio_listening_proxy,
    _prompt,
    is_audio_native_model,
    validate_audio_native_result,
)
from edmg_studio_backend.services.qwen_director import run_director_job


def document() -> DirectorDocument:
    return DirectorDocument(scenes=[SceneSpec(
        scene_id="scene-1", start_sample="0", end_sample="48000",
        intent="Opening", actions=["baseline"], camera=Camera(), environment=Environment(),
    )])


def test_audio_native_result_persists_semantics_and_scene_evidence():
    proposal, semantic, transcript = validate_audio_native_result({
        "semantic_interpretation": {
            "central_meaning": "Recovery after loss", "motifs": ["dawn"],
            "emotional_arc": [{"start_seconds": 0, "end_seconds": 1, "emotion": "hope"}],
        },
        "transcript_evidence": {"text": "I can begin again", "segments": []},
        "scenes": [{
            "scene_id": "scene-1", "actions": ["The subject steps into dawn"],
            "placement_reason": "The lyric resolves the central conflict.",
            "audio_evidence": [{"type": "lyric", "start_seconds": 0, "end_seconds": 1,
                                "detail": "I can begin again"}],
        }],
    }, document())

    assert semantic["central_meaning"] == "Recovery after loss"
    assert transcript["text"] == "I can begin again"
    assert proposal.scenes[0].actions == ["The subject steps into dawn"]
    assert proposal.scenes[0].renderer_hints["placement_reason"].startswith("The lyric")
    assert proposal.scenes[0].start_sample == "0"
    assert proposal.scenes[0].end_sample == "48000"


def test_audio_native_result_requires_every_scene_mapping():
    with pytest.raises(ValueError, match="scene set"):
        validate_audio_native_result({
            "semantic_interpretation": {"central_meaning": "Meaning"},
            "transcript_evidence": {}, "scenes": [],
        }, document())


def test_audio_native_result_uses_authoritative_transcript_when_model_omits_echo():
    proposal, semantic, transcript = validate_audio_native_result({
        "semantic_interpretation": {"central_meaning": "Return after loss"},
        "scenes": [{"scene_id": "scene-1", "actions": ["A soldier returns"],
                    "placement_reason": "The refrain resolves.", "audio_evidence": []}],
    }, document(), fallback_transcript={"text": "Come marching home", "segments": []})

    assert semantic["central_meaning"] == "Return after loss"
    assert transcript["text"] == "Come marching home"
    assert proposal.scenes[0].actions == ["A soldier returns"]


def test_audio_native_prompt_emits_scenes_first_and_caps_free_form_output():
    prompt = _prompt(document(), "Follow the song", {"duration_s": 1.0})

    output_shape = prompt.split("REQUIRED OUTPUT SHAPE:\n", 1)[1]
    assert output_shape.index('"scenes"') < output_shape.index('"semantic_interpretation"')
    assert output_shape.index('"semantic_interpretation"') < output_shape.index('"transcript_evidence"')
    assert "at most 40 words each" in prompt
    assert "Do not repeat timestamped transcript segments" in prompt


def test_audio_native_result_accepts_fenced_json():
    proposal, semantic, _transcript = validate_audio_native_result("""```json
{"semantic_interpretation":{"central_meaning":"Release"},"transcript_evidence":{"text":""},"scenes":[{"scene_id":"scene-1","actions":["Light expands"],"placement_reason":"The music opens.","audio_evidence":[]}]}
```""", document())

    assert semantic["central_meaning"] == "Release"
    assert proposal.scenes[0].actions == ["Light expands"]


def test_audio_native_result_repairs_a_single_missing_object_comma():
    proposal, semantic, _transcript = validate_audio_native_result(
        '{"semantic_interpretation":{"central_meaning":"Release"},'
        '"transcript_evidence":{"text":""},"scenes":[{"scene_id":"scene-1",'
        '"actions":["Light expands"] "placement_reason":"The music opens.",'
        '"audio_evidence":[]}]}',
        document(),
    )
    assert semantic["central_meaning"] == "Release"
    assert proposal.scenes[0].actions == ["Light expands"]


def test_audio_native_result_repairs_common_python_style_model_json():
    proposal, semantic, _transcript = validate_audio_native_result(
        "{'semantic_interpretation':{'central_meaning':'Release'},"
        "'transcript_evidence':{'text':''},'scenes':[{'scene_id':'scene-1',"
        "'actions':['Light expands'],'placement_reason':'The music opens.',"
        "'audio_evidence':[]}]}",
        document(),
    )
    assert semantic["central_meaning"] == "Release"
    assert proposal.scenes[0].actions == ["Light expands"]


def test_audio_native_result_accepts_filled_contract_envelope():
    proposal, semantic, _transcript = validate_audio_native_result({
        "output_contract": {
            "semantic_interpretation": {"central_meaning": "Persistence"},
            "transcript_evidence": {"text": "keep going"},
            "scenes": [{"scene_id": "scene-1", "actions": ["A figure climbs"],
                        "placement_reason": "The refrain insists.", "audio_evidence": []}],
        }
    }, document())

    assert semantic["central_meaning"] == "Persistence"
    assert proposal.scenes[0].actions == ["A figure climbs"]


def test_text_only_model_cannot_satisfy_audio_native_request():
    assert is_audio_native_model("hf_qwen3_omni_30b_a3b_thinking_director")
    with pytest.raises(Exception, match="cannot listen"):
        run_director_job({
            "model_id": "hf_qwen3_vl_8b_director", "require_audio_native": True,
            "document": document().model_dump(mode="json"),
        }, object())


def test_automatic_30b_oom_can_retry_with_installed_audio_native_7b(tmp_path):
    class Models:
        @staticmethod
        def installed_path(model_id):
            return tmp_path if model_id == FALLBACK_AUDIO_NATIVE_MODEL_ID else None

    payload = {
        "model_id": "hf_qwen3_omni_30b_a3b_thinking_director",
        "mode": "automatic",
    }
    assert _automatic_oom_fallback_model(payload, Models()) == FALLBACK_AUDIO_NATIVE_MODEL_ID
    assert _automatic_oom_fallback_model({**payload, "mode": "quality"}, Models()) is None
    assert _automatic_oom_fallback_model(
        {**payload, "_audio_native_fallback_attempted": True}, Models()
    ) is None


def test_automatic_long_audio_selects_installed_7b_before_loading_30b(tmp_path):
    class Models:
        @staticmethod
        def installed_path(model_id):
            return tmp_path if model_id == FALLBACK_AUDIO_NATIVE_MODEL_ID else None

    payload = {
        "model_id": "hf_qwen3_omni_30b_a3b_thinking_director",
        "mode": "automatic",
        "audio_evidence": {"duration_s": 516.7},
    }
    assert _automatic_long_audio_model(payload, Models()) == FALLBACK_AUDIO_NATIVE_MODEL_ID
    assert _automatic_long_audio_model(
        {**payload, "audio_evidence": {"duration_s": 120}}, Models()
    ) is None
    assert _automatic_long_audio_model({**payload, "mode": "quality"}, Models()) is None


def test_long_audio_reserves_gpu_activation_memory():
    gib = 1024 ** 3

    class Cuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def device_count():
            return 3

        @staticmethod
        def get_device_properties(_index):
            return type("Properties", (), {"total_memory": 48 * gib})()

    torch = type("Torch", (), {"cuda": Cuda()})()
    budgets = _long_audio_max_memory({"audio_evidence": {"duration_s": 516.7}}, torch)
    assert budgets == {0: 8 * gib, 1: 8 * gib, 2: 8 * gib, "cpu": 96 * gib}
    assert _long_audio_max_memory({"audio_evidence": {"duration_s": 60}}, torch) is None


def test_long_audio_listening_proxy_keeps_short_audio_unchanged(tmp_path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"not-read-for-short-audio")
    resolved, factor = _long_audio_listening_proxy(
        source, {"audio_evidence": {"duration_s": 30}}
    )
    assert resolved == source
    assert factor == 1.0


def test_prompt_evidence_excludes_dense_signal_arrays():
    compact = _compact_prompt_evidence({
        "duration_s": 12.0,
        "features": {"bpm": 120.0, "energy_points": [0.1] * 1000, "nested": {"x": 1}},
        "transcript": {"text": "hello", "segments": [], "source_audio_path": "private"},
        "sections": [{"start": 0, "end": 12}],
    })
    assert compact["feature_summary"] == {"bpm": 120.0}
    assert compact["transcript"] == {"text": "hello", "segments": []}
    assert compact["sections"] == [{"start": 0, "end": 12}]
