# EDMG Unreal Bridge Importer

This folder contains the first Unreal-side consumer for EDMG Studio Unreal bridge bundles.

## What it does

`import_unreal_bridge_bundle.py` reads an exported Studio bundle and:

- builds a deterministic import plan from `bundle_manifest.json` and the Unreal payload files
- creates a `LevelSequence` asset in Unreal
- sets the sequence frame rate and playback range
- adds marked frames from the Studio bundle
- creates one spawnable `CineCameraActor` binding per shot
- creates matching camera cut sections for those shots
- writes `unreal_import_report.json` back into the bundle directory
- ensures the bundle has a `returned/` folder for Unreal render outputs

This is intentionally the first practical bridge, not a full plugin. It gives Unreal a real consumer for the exported Studio contract without making Unreal a required Studio runtime. Its scope is limited to cameras, cuts, markers, and plan metadata; it does not ingest all media, construct a finished scene, configure Movie Render Queue, or automate the editor.

## Current status

Finished now:

- Studio can preview, export, build an Unreal import plan, and import returned renders back into project outputs.
- Studio Forge reports the active project/variant handoff readiness and links users to the canonical Workspace and Outputs pages.
- This importer can consume the exported bundle and create a first-pass Level Sequence asset.
- Review owns Studio's existing OSC, MIDI, and WebSocket live-publisher controls and status.

Not finished:

- No verified in-editor Unreal smoke test on this machine.
- No packaged Unreal plugin or module.
- No direct Unreal Remote Control integration. The Review publishers are general Studio handoffs, not an Unreal control implementation.
- No Movie Render Queue (MRQ) setup or execution.
- No one-click Unreal render job launcher from Studio.
- No deeper Sequencer or scene build beyond cameras, cuts, markers, and plan metadata.
- No full editor, scene-build, or returned-render automation.

## Studio ownership and handoff

Studio Forge is a readiness and routing surface; it does not execute this importer or mutate project outputs. Use the canonical pages for the authoritative actions:

- `Workspace` for the active project, plan, and selected variant
- `Outputs` for Unreal preview, bundle export, import-plan generation, and returned-media import
- `Review` for OSC, MIDI, and WebSocket live-publisher controls

The bridge is optional and non-authoritative. A successful Studio-side preview or import plan is not proof that Unreal imported or rendered it.

## Bundle inputs

The importer expects these files inside the selected bundle directory:

- `bundle_manifest.json`
- `shot_manifest.json`
- `audio_markers.json`
- `style_packet.json`
- `render_handoff.json`
- `live_control_bridge.json`
- `return_contract.json`

## Dry run outside Unreal

You can inspect the import plan without Unreal:

```bash
uv run --project studio/edmg-studio/python_backend --frozen --extra cpu ^
  python studio/edmg-studio/tools/unreal/import_unreal_bridge_bundle.py ^
  --bundle-dir F:\path\to\bundle ^
  --dry-run ^
  --plan-json F:\path\to\bundle\unreal_import_plan.json
```

Studio can also generate the same `unreal_import_plan.json` directly from the Outputs page via `Build import plan`. Studio Forge links to that canonical surface rather than duplicating the action.

## Run inside Unreal Editor

Example:

```bash
UnrealEditor.exe "C:\Path\To\Project.uproject" ^
  -ExecutePythonScript="F:\DWCTGenerativeSoundStudio\studio\edmg-studio\tools\unreal\import_unreal_bridge_bundle.py --bundle-dir F:\path\to\bundle --content-path /Game/EDMG/Sequences"
```

Optional flags:

- `--asset-name MySequence`
- `--replace-existing`
- `--plan-json C:\temp\edmg_unreal_import_plan.json`

## Returned media contract

After Unreal renders the sequence, place the output files into:

- `<bundle>/returned/`

Then go back to Studio Outputs and click `Import returned media` for that bundle. Studio will copy the returned files into canonical project outputs and register them under `Unreal bridge returns`.
