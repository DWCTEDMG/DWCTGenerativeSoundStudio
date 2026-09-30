# EDMG Studio Audio-Native Director Blueprint

## Outcome

EDMG Studio shall use an audio-native reasoning model as Director's primary listener. The Director receives the complete project audio plus deterministic signal evidence, creates a semantic interpretation and timed scene draft, and exposes proof of provenance in the native WinUI 3 Workspace. Whisper is optional transcript verification, never the creative authority. The shared Timeline changes only through an explicit **Apply** action.

## Non-negotiable product rules

1. Analyze the complete decoded audio. Persist exact timing evidence: duration, tempo, beats, onsets, energy, silence, dynamics, transitions, and deterministic section boundaries.
2. Send the original audio and the complete evidence bundle to an audio-native Director. The default production target is `Qwen/Qwen3-Omni-30B-A3B-Thinking`; the supported low-footprint target is `Qwen/Qwen2.5-Omni-7B`.
3. Treat model-produced timestamps as interpretations. Deterministic signal timestamps remain authoritative for edit and motion placement.
4. Produce and persist a structured semantic interpretation: central meaning, perspective, addressee, motivation, literal versus metaphorical readings, emotional arc, lyrical and musical turning points, motifs, palette, subjects, environments, visual language, ending, confidence, and cited audio/transcript evidence.
5. Every timed scene shall identify its deterministic section, lyric/audio anchors, narrative purpose, continuity requirements, and reason for placement.
6. Whisper or another ASR engine may verify uncertain lyrics, preferably from a separated vocal stem. Failure or absence of Whisper must not prevent signal analysis or an audio-native Director run.
7. The UI must distinguish a deterministic baseline from an audio-native model draft and show the actual model, transcript source, verification state, semantic summary, emotional arc, motifs, and scene-to-evidence mappings.
8. Director generation and revision are draft operations. Only explicit review followed by **Apply Workspace draft** may mutate the shared Timeline.

## Architecture

```text
project audio
  |-- deterministic analyzer -> immutable timing evidence
  |-- optional vocal separation -> optional ASR verification
  `-- audio-native Director
        receives audio + full evidence + baseline scene constraints
        -> semantic interpretation
        -> timed scene updates with evidence citations
        -> reviewable Workspace draft
        -> explicit review
        -> explicit Apply
        -> shared Timeline
```

### Persisted analysis contract

`project.meta.analysis` retains the existing feature and transcript fields and adds:

- `signal_analysis`: completion state and deterministic analyzer identity.
- `transcript_evidence`: primary source, verifier source, verification state, disagreements, and confidence.
- `audio_native_director`: requested model, completion state, provenance, and semantic interpretation.

The fields are additive so older projects and clients remain readable.

### Director job contract

The queued Director payload includes:

- `audio_path` and its SHA-256 fingerprint.
- `audio_evidence`: complete normalized signal features, transcript, and deterministic scene/section anchors.
- `model_id`, explicit runtime settings, instruction, baseline document, and source revision.
- `require_audio_native=true` for audio-native requests. This must fail closed if the selected adapter cannot consume audio; it must never silently route to Qwen3-VL or ComfyUI.

The result includes:

- `provenance.input_modality = "audio+text"`.
- `provenance.model_id`, runtime, device map, audio hash, transcript source, and verifier state.
- `semantic_interpretation` using the schema above.
- Updated scenes containing `audio_evidence` and `placement_reason` in renderer hints without changing authoritative timing.

### Runtime and model management

- Catalog IDs:
  - `hf_qwen3_omni_30b_a3b_thinking_director`
  - `hf_qwen25_omni_7b_director`
- Local inference uses a dedicated worker process and Hugging Face Transformers/Qwen Omni utilities. It never loads on the WinUI thread or the backend request thread.
- The 30B MoE model uses automatic multi-GPU placement and per-device memory budgets. The 7B model is the supported lower-memory fallback selected explicitly or by readiness policy.
- The existing Qwen3-VL adapters remain supported as visual/text Director models but are labeled non-audio-native and cannot satisfy an audio-native request.

## Native WinUI experience

Workspace shall expose:

- An **Audio-native Director** selector with Automatic, Qwen3-Omni Thinking, Qwen2.5-Omni 7B, and legacy visual/text Qwen choices.
- Optional **Verify lyrics with Whisper** and **Separate vocals for verification** settings.
- A proof panel with signal analysis state, Director listening state/model, transcript source and verification, meaning/theme summary, perspective, emotional arc, recurring motifs, and draft provenance.
- Per-scene lyric/audio anchors and placement reason in the existing editable scene surface.
- Existing review and Apply controls unchanged in authority: generation cannot silently alter the Timeline.

## Failure policy

- Signal analysis can complete when transcription or Director inference fails.
- An audio-native request fails visibly when audio is missing, the selected model is not installed/ready, or the adapter cannot consume audio.
- Whisper failure is reported as `verification_failed`; it does not replace or erase the Director transcript.
- A stale analysis hash, source revision, Workspace fingerprint, or Director context digest blocks Apply.
- Existing applied Timeline content remains intact after every failed or canceled stage.

## Acceptance criteria

1. A project with audio can complete deterministic analysis with Whisper disabled or unavailable.
2. A genuine audio-native job receives a real audio path and returns `input_modality=audio+text` provenance.
3. The backend persists structured semantic interpretation and evidence-backed scene mappings.
4. The native Workspace displays the required proof and accurately labels baseline versus model-generated drafts.
5. Legacy Qwen3-VL cannot be reported as having listened to audio.
6. Review is required before Apply; Apply is required before Timeline mutation.
7. Backend contract/unit tests, WinUI core tests, and Release x64 XAML build pass without changing unrelated Electron TensorRT work.
