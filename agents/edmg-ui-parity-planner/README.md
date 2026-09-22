# EDMG UI-Parity Remediation Planner

A Python Microsoft Agent Framework hosted agent that converts EDMG Studio
Electron-to-native UI gaps into prioritized, testable remediation plans. It uses
the Responses protocol and preserves the existing FastAPI, Python, CUDA, and
TensorRT backend as the authoritative compute layer.

## Output contract

The planner returns:

- prioritized parity gaps and user impact
- affected UI surfaces and concrete remediation steps
- dependencies, risks, and acceptance criteria
- validation and release sequencing
- an explicit statement that backend conversion is out of scope

The agent is advisory only. It does not modify Studio or backend code.

## Run locally

Set the selected Foundry project endpoint and model deployment in the active
`azd` environment, then run:

```powershell
azd ai agent run --no-client
azd ai agent invoke --local "Plan remediation for the missing native timeline controls."
```

## Deploy and invoke

```powershell
azd deploy --no-prompt
azd ai agent invoke "Plan remediation for the missing native timeline controls."
```

The hosted service targets the `jonlong-1185` project configured in `azure.yaml`.

## Optional Studio-wide TensorRT capability

EDMG Studio supports optional TensorRT acceleration through the shared backend runtime manager. Studio settings provide the global switch; native Render controls can override the preference, precision, and fallback for an individual internal render. Turning TensorRT off preserves the original runtime and does not require TensorRT to be installed.

This area retains its existing runtime and workflow; the shared Studio policy applies only to eligible internal inference components. The SD1.5 VAE decoder has an adapter; other model components remain on their existing runtimes until separately converted and validated. Hosted providers, audio processing, compositing, and exports do not acquire a TensorRT dependency. See the [Studio-wide TensorRT blueprint](../../EDMG_TensorRT_Full_Studio_Wide_Blueprint.md) for component admission and validation requirements.
