# Legacy AUTOMATIC1111 / WebUI Audit

Audit target: `H:\Repositories\DWCTGenerativeSoundStudio` on `codex/Unified`

Comparison artifact inspected: `D:\Downloads\deforum-for-automatic1111-webui.zip`

The attached zip is a full A1111 Deforum extension tree with `install.py`, `preload.py`, `javascript/deforum.js`, `scripts/deforum_api.py`, and `scripts/deforum_helpers/*`. The Studio repo does not vendor that extension tree directly. What remains in Studio is a smaller legacy seam: a connector module, config stubs, tests, a stale submodule entry, and optional tooling/docs.

## Active runtime verdict

No active Studio runtime feature currently depends on AUTOMATIC1111 or `/sdapi/v1`.

This includes:

- internal video rendering
- active backend routes under `edmg_studio_backend/app.py`
- ComfyUI integrations
- Electron / React surfaces

Studio does actively use EDMG Core for:

- Deforum template export
- prompt orchestration
- motion schedule generation
- creative-direction preview payloads

Those are Deforum-compatible planning/export features, not A1111 runtime dependencies.

## Reference inventory

| Path | Reference | Classification | Notes |
| --- | --- | --- | --- |
| `.gitmodules` | `external/stable-diffusion-webui` submodule | dead legacy code | No matching `external/` checkout or active import path in Studio |
| `studio/edmg-studio/python_backend/enhanced_deforum_music_generator/integrations/a1111_connector.py` | embedded A1111 imports, Deforum-extension detection, `/sdapi/v1/*` REST calls | optional/dev-only | Only imported by tests and the top-level compatibility shim |
| `studio/edmg-studio/python_backend/integrations/a1111_connector.py` | compatibility shim | dead legacy code | No active Studio runtime imports |
| `tests/test_a1111_connector.py` | connector tests | optional/dev-only | Duplicate of package-local test file |
| `studio/edmg-studio/python_backend/enhanced_deforum_music_generator/tests/test_a1111_connector.py` | connector tests | optional/dev-only | Valid only for the optional connector module |
| `studio/edmg-studio/python_backend/enhanced_deforum_music_generator/config/config_system.py` | `A1111Config` dataclass | optional/dev-only | Supports the connector tests and optional standalone tooling |
| `studio/edmg-studio/python_backend/enhanced_deforum_music_generator/config_system_complete.py` | `A1111Config`, `DEFORUM_A1111_*` env vars | optional/dev-only | Not used by the active Studio renderer |
| `studio/edmg-studio/python_backend/enhanced_deforum_music_generator/custom.yaml` | `a1111:` config block | optional/dev-only | Optional standalone EDMG config |
| `studio/edmg-studio/python_backend/enhanced_deforum_music_generator/integrations/hf_model_manager.py` | `wire_hf_video_model_to_a1111()` | optional/dev-only | Tooling convenience for external A1111 installs |
| `studio/edmg-studio/python_backend/enhanced_deforum_music_generator/cli/hf_models.py` | `--a1111-root` and A1111 wiring output | optional/dev-only | CLI-only |
| `studio/edmg-studio/python_backend/enhanced_deforum_music_generator/utils/utils_modules.py` | A1111/Deforum quickstart copy | dead legacy code | User-facing text only, not a Studio runtime path |
| `studio/edmg-studio/python_backend/pyinstaller.spec` | previously swept legacy connector modules into packaged backend | active packaging debt | Cleaned up in this patch by excluding proven-unused A1111 modules from the packaged runtime |

## Import and callsite trace

Observed A1111 connector imports/callsites:

- `studio/edmg-studio/python_backend/enhanced_deforum_music_generator/integrations/a1111_connector.py`
- `studio/edmg-studio/python_backend/integrations/a1111_connector.py`
- `tests/test_a1111_connector.py`
- `studio/edmg-studio/python_backend/enhanced_deforum_music_generator/tests/test_a1111_connector.py`

Not found in active Studio runtime:

- `edmg_studio_backend/app.py`
- `edmg_studio_backend/services/internal_video.py`
- React app under `studio/edmg-studio/src`
- ComfyUI runtime integrations

## Feature dependency trace

### Internal video renderer

Depends on:

- `edmg_studio_backend/services/internal_video.py`
- internal Diffusers / hosted / proxy logic
- timeline and plan data

Does not depend on:

- `A1111Connector`
- `/sdapi/v1` endpoints
- the A1111 WebUI extension runtime

### ComfyUI integrations

Depends on:

- `edmg_studio_backend/integrations/comfyui*`
- EDMG helper tooling for model wiring

Does not depend on:

- the A1111 connector runtime

### Active backend routes

Relevant active routes:

- `/v1/projects/{project_id}/render/internal/video`
- `/v1/projects/{project_id}/render/internal/preflight`
- `/v1/projects/{project_id}/render/comfyui/motion_scenes`
- `/v1/projects/{project_id}/render/stills/scenes`
- `/v1/projects/{project_id}/pipeline/run`
- `/v1/projects/{project_id}/export/deforum`
- `/v1/edmg/deforum_template`

None of these route paths import the A1111 connector.

## Safe-delete list

These are the lowest-risk removals once you choose to do a deletion pass:

- `.gitmodules` entry for `external/stable-diffusion-webui`
- `studio/edmg-studio/python_backend/integrations/a1111_connector.py`
- `tests/test_a1111_connector.py` if package-local optional connector tests remain

## Risky-delete list

These should not be removed without a separate decision on optional EDMG tooling support:

- `studio/edmg-studio/python_backend/enhanced_deforum_music_generator/integrations/a1111_connector.py`
- `studio/edmg-studio/python_backend/enhanced_deforum_music_generator/config/config_system.py` `A1111Config`
- `studio/edmg-studio/python_backend/enhanced_deforum_music_generator/config_system_complete.py` A1111 settings
- `studio/edmg-studio/python_backend/enhanced_deforum_music_generator/custom.yaml` `a1111:` section
- `studio/edmg-studio/python_backend/enhanced_deforum_music_generator/integrations/hf_model_manager.py` A1111 wiring helper
- `studio/edmg-studio/python_backend/enhanced_deforum_music_generator/cli/hf_models.py` A1111 wiring CLI option
- `studio/edmg-studio/python_backend/enhanced_deforum_music_generator/tests/test_a1111_connector.py`

## Minimal cleanup patch applied

This patch does not delete source files.

It does one proven-safe cleanup only:

- `studio/edmg-studio/python_backend/pyinstaller.spec`
  - exclude `integrations.a1111_connector`
  - exclude `enhanced_deforum_music_generator.integrations.a1111_connector`

That reduces packaged runtime drift without removing optional dev-only source.
