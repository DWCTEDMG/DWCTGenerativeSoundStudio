export function isFeatureEnabled(value: unknown): boolean {
  const normalized = String(value ?? "").trim().toLowerCase();
  return normalized === "1" || normalized === "true";
}

export function isStudioForgeEnabled(): boolean {
  return isFeatureEnabled(import.meta.env.VITE_EDMG_ENABLE_STUDIO_FORGE);
}
