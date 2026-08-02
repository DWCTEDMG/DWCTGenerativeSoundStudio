import { afterEach, describe, expect, it, vi } from "vitest";
import { isFeatureEnabled, isStudioForgeEnabled } from "../features";

const ORIGINAL_STUDIO_FORGE_FLAG = import.meta.env.VITE_EDMG_ENABLE_STUDIO_FORGE;
const ORIGINAL_STUDIO_FORGE_DISABLE_FLAG = import.meta.env.VITE_EDMG_DISABLE_STUDIO_FORGE;

describe("feature flags", () => {
  afterEach(() => {
    vi.stubEnv("VITE_EDMG_ENABLE_STUDIO_FORGE", ORIGINAL_STUDIO_FORGE_FLAG ?? "");
    vi.stubEnv("VITE_EDMG_DISABLE_STUDIO_FORGE", ORIGINAL_STUDIO_FORGE_DISABLE_FLAG ?? "");
  });

  it("keeps generic flags off but exposes Studio Forge by default", () => {
    expect(isFeatureEnabled(undefined)).toBe(false);
    expect(isFeatureEnabled("")).toBe(false);
    vi.stubEnv("VITE_EDMG_ENABLE_STUDIO_FORGE", "");
    vi.stubEnv("VITE_EDMG_DISABLE_STUDIO_FORGE", "");
    expect(isStudioForgeEnabled()).toBe(true);
  });

  it("accepts truthy generic flags and the legacy Forge enable override", () => {
    expect(isFeatureEnabled("1")).toBe(true);
    expect(isFeatureEnabled("true")).toBe(true);

    vi.stubEnv("VITE_EDMG_ENABLE_STUDIO_FORGE", "1");
    expect(isStudioForgeEnabled()).toBe(true);

    vi.stubEnv("VITE_EDMG_ENABLE_STUDIO_FORGE", "true");
    expect(isStudioForgeEnabled()).toBe(true);
  });

  it("supports an explicit kill switch and preserves a legacy false override", () => {
    vi.stubEnv("VITE_EDMG_ENABLE_STUDIO_FORGE", "");
    vi.stubEnv("VITE_EDMG_DISABLE_STUDIO_FORGE", "1");
    expect(isStudioForgeEnabled()).toBe(false);

    vi.stubEnv("VITE_EDMG_DISABLE_STUDIO_FORGE", "");
    vi.stubEnv("VITE_EDMG_ENABLE_STUDIO_FORGE", "0");
    expect(isStudioForgeEnabled()).toBe(false);

    vi.stubEnv("VITE_EDMG_ENABLE_STUDIO_FORGE", "1");
    vi.stubEnv("VITE_EDMG_DISABLE_STUDIO_FORGE", "true");
    expect(isStudioForgeEnabled()).toBe(false);
  });
});
