# Optional TensorRT expansion roadmap

Status: deferred future-version upgrade

Current implementation reference: [TENSORRT_RUNTIME_INTEGRATION.md](TENSORRT_RUNTIME_INTEGRATION.md)

Accelerator policy reference: [STUDIO_ACCELERATOR_POLICY.md](STUDIO_ACCELERATOR_POLICY.md)

## Purpose

This document records the planned expansion of NVIDIA TensorRT across EDMG Studio. It is a future-version roadmap, not a statement of current capability, a release commitment, or evidence that any listed model or operation already uses TensorRT.

TensorRT must remain optional. Existing CUDA providers remain available and authoritative whenever a TensorRT adapter, engine, validation receipt, runtime profile, or execution attempt is unavailable or unsuitable. No TensorRT upgrade may remove a working model, force a model through an unqualified engine, or silently select CPU as a substitute for requested GPU execution.

## Current-version boundary

The current managed TensorRT component runtime qualifies only these independently selectable SD1.5 components:

- SD1.5 UNet;
- SD1.5 VAE decoder.

SD1.5 text encoding and scheduling remain on the existing Diffusers/PyTorch path. Qwen remains on llama.cpp CUDA. Whisper remains on CTranslate2 CUDA. Other diffusion and video families retain their existing CUDA providers unless and until a future adapter meets every gate in this document.

The current Settings action **Optimize all compatible** means all buildable components registered by the current qualified adapter set. It does not mean every installed model is automatically TensorRT-compatible.

## Required product behavior

The future upgrade must satisfy all of the following:

1. TensorRT remains optional. Explicit TensorRT and Performance modes permit builds and selection according to their documented policy. Automatic mode may select only an already validated, beneficial engine when TensorRT is enabled and fallback is allowed; disabling TensorRT prohibits selection. Compatibility, PyTorch CUDA, and CPU modes never acquire TensorRT implicitly.
2. Every installed model receives a native WinUI status row. Models recognized by a discovery-capable adapter expose model-specific components in the TensorRT target selector; unrecognized architectures remain visible as adapter-unavailable rather than disappearing or receiving guessed component contracts.
3. Component discovery does not imply compatibility. A component becomes buildable only when a model-family adapter recognizes the exact architecture, weights, configuration, graph mutations, precision, and input profile.
4. **Optimize all compatible** discovers installed models and queues builds for every component qualified by an installed adapter.
5. Unsupported components retain their existing PyTorch CUDA, llama.cpp, CTranslate2, external-provider, or other established runtime without losing functionality.
6. A build, diagnostic, benchmark, cached engine, or validated engine is not proof that a render used TensorRT.
7. Studio reports active TensorRT acceleration only when an operation-specific receipt proves that the selected engine was loaded and executed.
8. A failed build, validation failure, incompatible profile, unsupported mutation, corrupt cache record, worker failure, or runtime error follows the configured fallback policy. An operation is successful only after either the selected TensorRT result or the established fallback-provider result succeeds. Strict mode may fail instead of falling back.
9. Native WinUI controls must expose discovery, compatibility, build, validation, cache, fallback, and receipt state. Backend-only capability is incomplete.
10. Existing model weights and user assets are never deleted by engine cleanup, rebuild, quarantine, or fallback.

## Architecture direction

Use an explicit model-family adapter framework. Runtime introspection may discover candidate components, but only a registered adapter may declare a component compatible or buildable.

Each adapter owns:

- installed-model recognition and immutable model identity;
- component discovery and user-facing component names;
- graph extraction or export;
- named input and output bindings;
- minimum, optimum, and maximum shape profiles;
- supported batches, resolutions, frame counts, sequence lengths, and precisions;
- conditioning, guidance, timestep, rotary-position, temporal, and latent inputs;
- graph-mutation compatibility for LoRA, ControlNet, IP Adapter, custom VAE, merged weights, quantization, and other modifications;
- engine compilation and content-addressed identity fields;
- deterministic reference inputs;
- numerical and task-level validation thresholds;
- benchmark and benefit policy;
- runtime loading, invocation, disposal, and fallback;
- execution evidence contributed to the final operation receipt.

The lifecycle is:

```text
Installed model
    |
    v
Discover model-specific components
    |
    v
Qualified adapter available?
    |-- no --> Existing validated provider
    '-- yes
         |
         v
Exact graph/profile/mutations buildable?
    |-- no --> Existing validated provider
    '-- yes
         |
         v
Build content-addressed engine
         |
         v
Validate numerical and task-level output
    |-- fail --> Quarantine engine and use fallback policy
    '-- pass
         |
         v
Engine eligible for matching operations
         |
         v
Load and execute engine
         |
         v
Write receipt-backed TensorRT execution evidence
```

## Model-generation adapters

### Image diffusion families

Add explicit adapters for:

- SDXL UNet and VAE components;
- SD3 and SD3.5 transformer and VAE components;
- Flux transformer and VAE components;
- other installed image-generation families only after their graph contracts are explicitly implemented.

Text encoders may remain on their existing CUDA provider when TensorRT compilation is not beneficial or not qualified. A hybrid pipeline is acceptable and must report component-level provenance.

Profiles must cover only explicitly validated resolution, batch, prompt-embedding, guidance, and latent-shape ranges. Studio must not infer compatibility solely because two models use a component named `transformer`, `unet`, or `vae_decoder`.

### Video-generation families

Add explicit temporal adapters for:

- Stable Video Diffusion;
- AnimateDiff;
- LTX-Video 2.5;
- Wan;
- HunyuanVideo 1.5;
- later installed video families after separate qualification.

Video adapters must account for temporal dimensions, frame count, latent layout, text and image conditioning, motion inputs, rotary embeddings, guidance, multi-GPU memory behavior, and bounded dynamic shapes.

Tensor-level validation alone is insufficient for video qualification. Each adapter ultimately requires a real output with:

- successful engine deserialization and invocation evidence;
- expected frame count and dimensions;
- finite decoded frames;
- temporal and motion-quality checks appropriate to the model;
- `ffprobe`-validated video and audio streams when the workflow promises both;
- source, model, segment or motion, component-engine, and final-output receipts.

### Qwen and other language-model paths

Qwen language generation remains on llama.cpp CUDA by default. A future TensorRT-LLM integration must be a separate provider with its own installation, model-format, quantization, context, sampling, multi-GPU, and receipt contracts. It must not be presented as part of the diffusion component runtime.

Potential hybrid acceleration may cover a compatible vision encoder or multimodal projector while llama.cpp continues language generation. Such a path requires exact embedding-equivalence validation against the loaded Qwen model and explicit hybrid provenance.

### Whisper and speech paths

Whisper remains on the validated CTranslate2 CUDA provider unless a purpose-built TensorRT speech adapter demonstrates a material benefit without degrading transcription accuracy, timestamps, language detection, or cancellation behavior.

Potential components include:

- audio encoder;
- token decoder;
- neural voice-activity detection;
- punctuation or diarization models.

Provider benchmarks must include end-to-end transcription behavior, not only isolated kernel timing.

## Analysis and creative-tool adapters

### Image and video analysis

Candidate optional TensorRT adapters include:

- object detection;
- face detection and landmark tracking;
- person, semantic, and instance segmentation;
- depth estimation;
- human pose estimation;
- scene classification;
- learned shot-boundary classification;
- image and video embeddings;
- visual-similarity and duplicate detection;
- content and safety classification;
- aesthetic-quality scoring;
- video-captioning vision encoders;
- optical-flow networks;
- learned camera-motion estimation.

These capabilities may support Workspace, Director, Storyboard, Reactive Lab, Review, media ingestion, and asset organization. Traditional metadata parsing, histogram calculation, deterministic resizing, and simple pixel-difference analysis remain outside TensorRT.

### Neural video post-processing

Candidate independent post-processing adapters include:

- frame interpolation;
- neural upscaling and super-resolution;
- video denoising;
- deblurring;
- compression-artifact reduction;
- face restoration;
- neural colorization;
- learned tone mapping;
- learned stabilization;
- slow-motion synthesis;
- alpha matting;
- background removal.

Post-processing must be independently optional. Failure must preserve the original render or use the established CUDA implementation according to policy. Receipts must identify the post-processing model, engine, profile, processed frame range, and fallback decisions.

### Audio and music intelligence

Candidate neural audio adapters include:

- source separation and stem extraction;
- music tagging;
- instrument and vocal recognition;
- speaker or singer embeddings;
- neural beat and downbeat detection;
- chord recognition;
- mood and genre classification;
- audio embeddings and similarity;
- neural denoising and speech enhancement;
- learned mastering or mix-assistance models.

Conventional audio decoding, resampling, FFT analysis, peak detection, loudness measurement, mixing, panning, equalization, compression, delay compensation, MIDI, AudioGraph processing, and VST3 hosting remain in their existing native or DSP paths. TensorRT is not a general-purpose audio engine.

### Semantic search and organization

TensorRT may accelerate embedding or classification models used for:

- semantic media search;
- similar-shot and similar-image search;
- audio similarity;
- automatic tagging;
- subject or character clustering;
- project-asset recommendations;
- matching storyboard prompts to existing media;
- reusable-analysis discovery across projects.

Database indexing and similarity search remain separate from TensorRT. Only the neural embedding or classification inference is eligible.

### Review and quality control

Candidate adapters include:

- learned black-frame or corruption detection;
- flicker detection;
- temporal-consistency scoring;
- lip-sync scoring;
- motion-quality scoring;
- image and video quality assessment;
- compression-artifact detection;
- content-policy classifiers;
- watermark and logo detection.

Deterministic validation such as stream presence, codec, duration, resolution, frame count, audio levels, file hashes, and `ffprobe` checks remains authoritative and outside TensorRT.

### Neural previews and proxies

Candidate preview adapters include:

- low-resolution draft generation;
- latent previews;
- fast keyframe previews;
- storyboard thumbnails;
- proxy upscaling;
- lightweight motion previews;
- learned render-quality estimation.

Preview artifacts must be clearly labeled as proxies. A successful preview must never be represented as a full-quality or final model render.

## Workloads outside TensorRT scope

TensorRT must not be presented as accelerating:

- WinUI layout, page navigation, or application startup;
- project-file operations, undo/redo, or timeline editing;
- job-queue bookkeeping, JSON processing, APIs, or database access;
- model downloads or WSL/process orchestration;
- ordinary file copying;
- FFmpeg muxing or deterministic media validation;
- conventional audio mixing, DSP, MIDI, or VST3 processing;
- video encoding or decoding by itself.

NVENC and NVDEC are separate NVIDIA technologies for video encode/decode. General CUDA computation is also separate from TensorRT neural-network inference. The UI and receipts must use these terms accurately.

## Native Studio experience

The native WinUI experience must provide:

- an installed-model and component selector populated from live backend discovery;
- clear `unsupported`, `fallback-only`, `buildable`, `building`, `validated`, `quarantined`, and `executed` states;
- adapter name and version;
- supported profile ranges and precision choices;
- mutation compatibility and reasons for exclusion;
- **Optimize selected**, **Optimize all compatible**, **Rebuild**, **Validate**, and safe cache removal;
- job progress, cancellation, and bounded logs through the existing queue;
- engine identity and validation receipts;
- render- or operation-specific execution provenance;
- clear separation between TensorRT component acceleration, TensorRT-LLM, llama.cpp, CTranslate2, PyTorch CUDA, NVENC/NVDEC, and ordinary CPU work.

Specialist pages remain available. Workspace may provide the guided path, but Models, Settings, Render, Render Queue, Review, Outputs, Director, Storyboard, Reactive Lab, and Timeline retain their appropriate expert controls and provenance views.

## Optimize-all contract

**Optimize all compatible** must:

1. enumerate installed and admitted models;
2. ask registered adapters to discover exact buildable components;
3. exclude unsupported architectures, incompatible graph mutations, unqualified profiles, and missing dependencies with explicit reasons;
4. create independently cancellable jobs through the existing queue;
5. serialize conflicting model access through the existing admission lock;
6. build content-addressed engines without overwriting other identities;
7. validate every engine before publishing it as ready;
8. quarantine failed or corrupt engines;
9. preserve model weights, source assets, older nonmatching engines, and working fallback providers;
10. return a batch receipt containing per-component success, failure, exclusion, and fallback information.

A batch operates on an immutable discovery snapshot containing model identities, component identities, adapter versions, profiles, and mutations. Models installed, removed, or changed after snapshot creation are excluded from that batch and appear on the next discovery. The model/component/engine identity is the idempotency key: an equivalent active job is reused, a validated exact engine is skipped unless rebuild was explicitly requested, and retry creates a new attempt without changing the identity.

Jobs declare resource requirements and obey bounded per-GPU concurrency and model-admission locking. Adapter-declared dependency ordering is honored. Cancellation stops unstarted work, requests cancellation of active work, preserves already published validated engines, and records canceled components separately from failed or excluded components. After process restart, persisted terminal results remain authoritative and incomplete jobs resume or terminate according to the existing queue recovery contract. Optimize-all itself never deletes older nonmatching engines; explicit cache policy may remove selected managed artifacts independently.

A partial batch may succeed. Batch status is `completed`, `completed_with_issues`, `canceled`, or `failed`, derived from its per-component terminal states. Studio must show exactly which components were qualified and must not promote excluded, canceled, or failed components.

## Engine identity and cache safety

Engine identities must include at least:

- stable model ID and immutable weight/configuration hashes;
- model family and component;
- adapter name and version;
- graph-mutation identity;
- compiler, framework, ONNX when applicable, TensorRT, CUDA, and plugin versions;
- GPU name, UUID, and compute capability;
- precision and optimization profiles;
- named binding schemas;
- validation schema and thresholds.

Cache lookup requires an exact identity, manifest validation, engine checksum, matching runtime environment, and a passing validation receipt. Cache cleanup removes only managed engine artifacts selected by policy; it never removes models or user media.

## Validation requirements

Every adapter requires layered validation:

1. **Export validation** — graph and bindings match the adapter contract.
2. **Build validation** — TensorRT compiles and serializes an engine for the declared profiles.
3. **Deserialization validation** — a fresh worker loads the exact serialized engine.
4. **Numerical validation** — fixed reference inputs compare the existing provider with TensorRT using component-specific metrics and thresholds.
5. **Profile validation** — minimum, optimum, and maximum supported shapes execute with finite outputs.
6. **Mutation validation** — supported mutations are represented in engine identity; unsupported mutations force fallback.
7. **Benchmark validation** — component and end-to-end measurements determine whether automatic selection is beneficial.
8. **Integration validation** — the owning model pipeline consumes the TensorRT output correctly.
9. **Artifact validation** — generated images, audio, or video pass format-appropriate quality and stream checks.
10. **Receipt validation** — the final operation records actual engine loading and execution rather than planned routing.

Tests with mocks or synthetic engines establish contracts but do not qualify a production model. Each release candidate needs fresh candidate-bound hardware evidence for every capability it claims.

## Execution receipt contract

TensorRT execution evidence is component-scoped. A component may report `tensorrt_executed: true` only when at least one successful invocation occurred and the output from that exact invocation was consumed by the completed pipeline result. Operation-wide summaries are derived from the component records and must not hide mixed TensorRT and fallback execution.

If TensorRT executes but its output is rejected, discarded, or replaced by fallback, the component records `tensorrt_attempted: true`, `tensorrt_executed: true`, `tensorrt_output_consumed: false`, and the terminal provider that produced the accepted output. Such a component does not count as TensorRT-accelerated in the operation summary. A successful TensorRT component records `tensorrt_output_consumed: true` and binds the invocation output through component-output lineage to the final artifact or accepted analysis result.

The receipt schema is versioned and atomically persisted. Failure to persist required execution evidence prevents an acceleration claim even when inference succeeded. The receipt must include:

- operation and job IDs;
- project and output IDs where applicable;
- model ID, immutable model identity, family, and component;
- adapter name and version;
- engine ID and checksum;
- precision and selected optimization profile;
- TensorRT and CUDA versions;
- GPU identity;
- engine load result;
- component attempt and invocation IDs;
- successful inference invocation count, which must be at least one for executed state and must exclude failed invocations;
- `tensorrt_attempted`, `tensorrt_executed`, and `tensorrt_output_consumed` states;
- terminal accepted provider and whether fallback replaced a TensorRT result;
- component-output and final-artifact lineage references;
- processed frame, sample, segment, or batch range;
- benchmark or timing information when measured;
- graph-mutation identity;
- fallback decisions and causes;
- validation-receipt reference;
- receipt schema version, writer identity, creation timestamp, and integrity hash;
- final artifact references and media-validation results where applicable.

Installed, available, healthy, compatible, cached, built, and validated remain separate states. None substitutes for executed.

## Delivery phases

The future upgrade should be delivered as independently testable phases:

1. Shared model-family adapter contract, discovery, status, receipts, and dynamic WinUI selection.
2. SDXL UNet and VAE adapters, building on the existing SD1.5 component design.
3. SD3/SD3.5 and Flux transformer/VAE adapters.
4. Independent analysis and post-processing adapters such as depth, segmentation, upscaling, and frame interpolation.
5. LTX-Video temporal adapters and full video qualification.
6. SVD, AnimateDiff, Wan, and HunyuanVideo temporal adapters with per-family validation.
7. Optional neural audio-analysis adapters.
8. Optional search, review, quality-control, and proxy-generation adapters.
9. Separately scoped TensorRT-LLM or hybrid Qwen vision work if benchmarks justify it.
10. Separately scoped TensorRT Whisper work only if it outperforms the validated CTranslate2 path without accuracy loss.

Each release selects a closed set of model families, components, profiles, mutations, operating systems, GPU architectures, drivers, and fixtures from these phases. Open-ended phrases such as later model families are backlog direction, not part of a release completion claim.

Every phase has an acceptance matrix that identifies its exact models and immutable revisions, component profiles, reference corpus, numerical and task-level thresholds, repeat count and variance allowance, latency/throughput/VRAM benchmarks, required hardware, fallback and strict-mode tests, cancellation and restart tests, WinUI tests, packaged clean-machine tests, and receipt-lineage assertions. Thresholds and the benefit rule must be numeric and adapter-versioned before qualification begins.

Each phase must leave the Studio usable when TensorRT is disabled, unavailable, incompatible, or failing.

## Completion criteria

The roadmap is complete only when:

- every claimed model family has a real adapter, not only a catalogue row;
- installed compatible components appear in native WinUI;
- optimize-all builds and validates every qualified installed component;
- unsupported components retain their established providers;
- fallback and strict modes behave predictably;
- cached engines are content-addressed and safely invalidated;
- real operations consume adapter outputs;
- operation receipts prove actual engine loading and inference;
- generated artifacts pass model-appropriate and media-appropriate validation;
- packaged, signed, installed, and clean-machine candidates repeat the claimed behavior;
- documentation distinguishes current capability, future capability, diagnostics, validation, and execution evidence.

Until these criteria are met for a specific adapter, Studio must describe that component as unsupported or fallback-only and must not imply TensorRT acceleration.
