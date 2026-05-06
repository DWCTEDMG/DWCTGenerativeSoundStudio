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

This is intentionally the first practical bridge, not a full plugin. It gives Unreal a real consumer for the exported Studio contract without making Unreal a required Studio runtime.

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
python studio/edmg-studio/tools/unreal/import_unreal_bridge_bundle.py ^
  --bundle-dir F:\path\to\bundle ^
  --dry-run ^
  --plan-json F:\path\to\bundle\unreal_import_plan.json
```

Studio can also generate the same `unreal_import_plan.json` directly from the Outputs page via `Build import plan`.

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
