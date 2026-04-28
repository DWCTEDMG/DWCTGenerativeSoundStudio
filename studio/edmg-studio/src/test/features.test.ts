import { afterEach, describe, expect, it, vi } from "vitest";
import { isFeatureEnabled, isStudioForgeEnabled } from "../features";

const ORIGINAL_STUDIO_FORGE_FLAG = import.meta.env.VITE_EDMG_ENABLE_STUDIO_FORGE;

describe("feature flags", () => {
  afterEach(() => {
    vi.stubEnv("VITE_EDMG_ENABLE_STUDIO_FORGE", ORIGINAL_STUDIO_FORGE_FLAG ?? "");
  });

  it("returns false by default", () => {
    expect(isFeatureEnabled(undefined)).toBe(false);
    expect(isFeatureEnabled("")).toBe(false);
    expect(isStudioForgeEnabled()).toBe(false);
  });

  it("returns true for 1 or true", () => {
    expect(isFeatureEnabled("1")).toBe(true);
    expect(isFeatureEnabled("true")).toBe(true);

    vi.stubEnv("VITE_EDMG_ENABLE_STUDIO_FORGE", "1");
    expect(isStudioForgeEnabled()).toBe(true);

    vi.stubEnv("VITE_EDMG_ENABLE_STUDIO_FORGE", "true");
    expect(isStudioForgeEnabled()).toBe(true);
  });
});
