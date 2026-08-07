# Triton Provider Readiness

Last reviewed: 2026-08-06

## Release decision

NVIDIA Triton Inference Server is **not a required dependency** of the EDMG Studio 1.2.0 desktop
release candidate. The canonical CUDA desktop profile runs its backend locally and already bundles the
locked CUDA, PyTorch, TensorRT, and Torch-TensorRT runtime selected by
`studio/edmg-studio/python_backend/pyproject.toml` and its `uv.lock`.

An operator may run a separate inference service for research, but Studio must continue to install,
launch, plan, render, cancel, recover, and report readiness when that service is absent.

## TensorRT is not Triton

- **TensorRT / Torch-TensorRT** optimize and execute models inside the packaged Studio backend.
- **Triton Inference Server** is a separate model-serving process with its own model repository,
  protocols, lifecycle, authentication, queueing, and deployment evidence.
- Shipping TensorRT support does not imply that a Triton server is installed.
- Running a Python FastAPI process inside a Triton container image does not, by itself, use Triton
  model serving.

The locally inspected 1.1.0 CUDA installation contains TensorRT 10.15.1.29, Torch-TensorRT,
CUDA Python 13.0.3, and PyTorch 2.11.0+cu130. Its release manifest does not declare a Triton
runtime. That installation is the previous-version upgrade baseline, not the 1.2.0 candidate; its
runtime shape is nevertheless the expected architecture for the current local renderer.

The inspected installation contains no `.engine`, `.plan`, or `.onnx` model artifact. Runtime
libraries being present must therefore be reported separately from a ready TensorRT model bundle.
Studio's TensorRT render path remains capability-gated on an installed bundle containing a usable,
non-empty engine.

The Models page may detect and copy the recognized root-level legacy engines under the active
Studio Home into the canonical local bundle. That source-preserving compatibility migration is
local TensorRT housekeeping, not Triton discovery or provider promotion, and an engine-only copy
remains not renderer-ready until all required assets and metadata are verified.

## Current external prototype classification

The operator-supplied Triton setup is classified as **research / external prototype**, not as a
release component. The inspected service:

- overrides the Triton image entry point and launches a standalone FastAPI/uvicorn app;
- loads Stable Diffusion, Stable Video Diffusion, and AnimateDiff directly through Diffusers;
- installs Python dependencies ad hoc during the image build without a frozen lock or hashes;
- binds to all interfaces without a Studio authentication contract;
- returns raw exception details to callers;
- disables the Stable Diffusion safety checker;
- loads multiple large pipelines during startup;
- has no durable queue, lease, cancellation, restart recovery, or artifact provenance contract;
- writes temporary render directories without a bounded cleanup policy; and
- exposes port 8000, which can collide with older local OpenAI-compatible defaults.

Studio must not auto-discover, package, start, stop, or route customer renders to this prototype.

The current CUDA package is also a size-optimization candidate: its TensorRT distribution includes
approximately 1.9 GB of per-architecture builder resources in addition to the runtime libraries,
while the canonical Studio path only deserializes prebuilt engines. Do not remove those resources
until a focused packaged TensorRT smoke test proves that customer rendering, engine loading, and
supported GPU coverage remain intact. A future packaging split should keep the runtime in the
customer build and move compiler/builder tooling into an optional developer add-on.

## Promotion contract

A future Triton provider may move from `research` to `experimental` only after all of the following
are implemented and tested:

1. **Real Triton execution** — versioned model repository configs and Triton HTTP/gRPC inference,
   readiness, and model-control APIs are used rather than a sidecar merely inheriting its image.
2. **Reproducible supply chain** — container image is pinned by digest; Python packages, CUDA,
   TensorRT, model revisions, and artifacts are pinned and represented in an SBOM.
3. **Stable Studio adapter** — one provider contract covers capabilities, preflight, enqueue,
   progress, cancellation, failure, artifact collection, and provenance.
4. **Safe networking** — loopback is the local default; remote use requires TLS and bearer or
   stronger authentication; CORS and request sizes are allowlisted and bounded.
5. **Safe errors and logs** — public failures use stable codes, messages, and hints; tracebacks and
   secrets remain server-side and support bundles are redacted.
6. **Durable scheduling** — bounded concurrency, backpressure, cancellation, timeout, restart
   recovery, idempotency, and GPU-memory admission are proven.
7. **Model governance** — license, source, revision, checksum, input/output contract, VRAM tier,
   deterministic seed behavior, and fallback are declared in the canonical model catalog.
8. **Artifact discipline** — outputs are streamed or written through Studio artifact manifests;
   temporary frames are cleaned after success, cancellation, and failure.
9. **Studio UI** — Settings exposes the endpoint and credentials through secret storage, System
   Readiness reports it, Models shows compatibility, and Render explains provider selection and
   fallback. No raw JSON editing is required for normal operation.
10. **Evidence** — adapter conformance, failure injection, offline behavior, cancellation, recovery,
    security, quality, latency, and named-GPU benchmark suites pass.

Promotion from `experimental` to `recommended` additionally requires clean-machine deployment,
upgrade/rollback proof, a supported compatibility matrix, and regression evidence showing that the
provider improves a named workload without changing the canonical project or artifact formats.

## Future integration boundary

If promoted, Triton should be an optional provider behind the existing Studio backend:

```text
Studio UI
  -> EDMG Studio backend
     -> render plan and durable job store
        -> local internal/TensorRT provider (canonical default)
        -> optional Triton provider adapter
           -> authenticated Triton server
```

The UI and project format must never communicate with a Triton-specific schema directly. Provider
selection remains explainable and reversible, and failure falls back only when the render plan and
user settings permit it.
