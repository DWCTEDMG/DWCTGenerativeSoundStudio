from __future__ import annotations

import pytest

from edmg_studio_backend.domain.director_scene import (
    Camera,
    DirectorDocument,
    Environment,
    SceneSpec,
)
from edmg_studio_backend.services.audio_native_director import (
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


def test_audio_native_result_accepts_fenced_json():
    proposal, semantic, _transcript = validate_audio_native_result("""```json
{"semantic_interpretation":{"central_meaning":"Release"},"transcript_evidence":{"text":""},"scenes":[{"scene_id":"scene-1","actions":["Light expands"],"placement_reason":"The music opens.","audio_evidence":[]}]}
```""", document())

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
