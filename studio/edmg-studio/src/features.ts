export function isFeatureEnabled(value: unknown): boolean {
  const normalized = String(value ?? "").trim().toLowerCase();
  return normalized === "1" || normalized === "true";
}

export function isStudioForgeEnabled(): boolean {
  if (isFeatureEnabled(import.meta.env.VITE_EDMG_DISABLE_STUDIO_FORGE)) return false;

  // Preserve the original flag as a compatibility override for deployments that
  // already set it explicitly. New builds expose Forge by default and use the
  // disable flag as the intentional operator kill switch.
  const legacyOverride = String(import.meta.env.VITE_EDMG_ENABLE_STUDIO_FORGE ?? "").trim();
  return legacyOverride ? isFeatureEnabled(legacyOverride) : true;
}
