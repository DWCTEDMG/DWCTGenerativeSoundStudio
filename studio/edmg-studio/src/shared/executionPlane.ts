export type RuntimeProfile = "standard" | "hybrid_gpu" | "external_linux";
export type ExecutionEnvironment = "auto" | "windows" | "wsl" | "external";
export type ExecutionProfile = { runtime_profile: RuntimeProfile; model_environment_preferences: Record<string, "windows" | "wsl"> };
export type ExecutionReadiness = Record<"wsl_installed" | "distribution_running" | "worker_environment_present" | "gpu_visible" | "model_installed" | "worker_launchable" | "generation_started" | "artifact_validated" | "runtime_qualified", boolean>;
export type ExecutionInventory = { wsl: { configured: boolean; distribution?: string | null; readiness: ExecutionReadiness }; physical_gpus: Array<Record<string, unknown>>; blockers: Array<{ code: string; message: string }>; probe_performed: boolean };
export function executionReadinessLabel(inventory: ExecutionInventory): string {
  const state = inventory.wsl.readiness;
  if (state.runtime_qualified) return "Runtime qualified";
  if (state.worker_launchable) return "Worker launchable (not yet qualified)";
  if (state.model_installed) return "Model installed (worker blocked)";
  return "WSL execution blocked";
}
