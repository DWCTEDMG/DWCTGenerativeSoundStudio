# TensorRT bundle migration

EDMG Studio 1.2 recognizes the pre-canonical SD 1.5 TensorRT engine layout at:

```text
<Studio Home>/models/internal/tensorrt/*.engine
```

The supported destination is:

```text
<Studio Home>/models/internal/tensorrt/local_sd15_tensorrt_bundle/
  edmg-tensorrt-bundle.json
  engine/
    text_encoder.engine
    unet_b1_workspace4096.engine
    vae_decoder.engine
    vae_encoder.engine
  onnx/
```

## Safety contract

- Detection is read-only and scans only the direct legacy folder. Studio does not recursively discover unrelated drives, research sandboxes, Triton Server repositories, or arbitrary model directories.
- Migration begins only after an explicit **Verify and copy engines** action on the Models page.
- The four expected legacy engine roles must be present as safe, non-empty regular files.
- Studio verifies capacity for a complete second copy plus a safety reserve before copying.
- Each source is copied into a same-volume temporary bundle while SHA-256 is calculated. Studio then rereads and verifies every destination file.
- The canonical bundle is published only after every file and the schema-versioned manifest are complete.
- Cancellation and ordinary errors remove only the operation's temporary folder. They never remove or modify the legacy source.
- An existing canonical folder is never overwritten. A conflict requires operator review.

## Readiness is intentionally conservative

Copying engines does not by itself make the bundle renderer-ready. The Models page and backend report these states separately:

| Requirement | Engine copy | Renderer-ready bundle |
| --- | ---: | ---: |
| Four expected engine roles | Required | Required |
| Source and destination SHA-256 records | Required | Required |
| Valid EDMG manifest with unique, safe destinations | Required | Required |
| Complete manifest-listed ONNX component inventory | Not synthesized | Required |
| Verified compiled width, height, batch, and integer sample-size profile | Not inferred as verified | Required |
| Verified matching SD 1.5 Hub model ID and immutable revision | Not inferred as verified | Required |

The migration manifest records the legacy filename convention as unverified profile context only. It never converts that inference into a readiness claim. Model Manager does not advertise the canonical model as installed until the complete renderer-readiness check succeeds.

### Execution-ready manifest contract

Renderer readiness is derived only from explicit manifest sections; Studio does not promote a
bundle from `_name_or_path`, directory names, or arbitrary request/environment strings:

- `source.files` contains exactly one safe record for each of `text_encoder`, `unet`,
  `vae_decoder`, and `vae_encoder`. Every destination must be the matching direct child of
  `engine/`; its recorded size and verification-time modification stamp must still match, and its
  SHA-256 is reread before execution.
- `onnx.verified` is explicitly `true`, and `onnx.files` inventories every regular file under
  `onnx/` with a unique role, safe relative path, size, verification-time modification stamp, and
  SHA-256. The required inventory covers
  the model index, feature extractor, scheduler, text encoder, tokenizer, UNet, VAE decoder, and
  VAE encoder components. Unlisted, missing, empty, or symlinked files fail validation.
- `profile.verified` is explicitly `true`. `width`, `height`, `batch_size`, and `sample_size` are
  positive JSON integers, the currently supported batch is exactly one, and the UNet config's
  integer `sample_size` must agree with the manifest dimensions. Arrays are not accepted.
- `base_model.verified` is explicitly `true`. `id` is an unambiguous Hugging Face repository ID,
  and `revision` is an immutable 40-to-64-character commit hash. The model-index and any
  recognizable UNet export identity must match both fields.

The validator produces one immutable runtime contract containing the exact selected UNet engine,
ONNX component paths, compiled profile, and pinned base-model coordinates. Model resolution and
the standalone renderer consume that same contract. Before rendering, Studio rereads the four
engine files and verifies their SHA-256 values; it does not fall back to another engine discovered
elsewhere in the directory.

## Runtime path contract

Public render requests contain stable model IDs, never filesystem paths. The backend resolves an installed bundle path and passes that exact path through both supported execution flows:

1. dedicated SD 1.5 TensorRT keyframe-video rendering; and
2. SD 1.5 TensorRT storyboard anchors used by SVD or AnimateDiff internal video.

The internal Diffusers base path, the SVD/AnimateDiff model path, and the TensorRT anchor path remain separate values. Low-level rendering no longer treats a client-supplied `model_id` as a local path.

Environment-selected external bundles remain a transitional, explicit compatibility mechanism.
They are never auto-discovered or copied, and mere directory existence never marks them installed.
The canonical bundle is always evaluated first; an external override can be selected only when the
canonical bundle is unavailable or invalid and the external bundle passes the exact same manifest,
inventory, profile, model-revision, safe-path, and engine-hash contract. Models reports configured
external candidates as unverified until that succeeds. NVIDIA Triton Inference Server prototypes
are separate operator-managed systems and are not part of this migration or the packaged Studio
release.

## Compatibility removal gate

Keep root-level legacy detection for at least one supported release cycle after the Models-page migration ships. Remove it only when all of the following are true:

1. supported upgrades have had a documented opportunity to run the copy workflow;
2. release telemetry or support audits no longer find the root-level layout in active installations;
3. migration and rollback guidance has been published for the last supported legacy version; and
4. the canonical bundle validator and exact-path render handoffs are covered by release-gating tests.

Legacy source files are intentionally retained after a successful copy. Their eventual deletion is an explicit operator decision after the canonical bundle is completed and a real render has been verified; Studio does not automate that deletion.
