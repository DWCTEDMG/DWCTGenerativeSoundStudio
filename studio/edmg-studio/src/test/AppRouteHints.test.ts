import { describe, expect, it, vi } from "vitest";
import {
  getPageLoadingDetails,
  getPagesToPreload,
  runBestEffortPagePreload,
} from "../pageRouting";

describe("App route hints", () => {
  it("describes Studio Forge with page-specific loading copy", () => {
    const loading = getPageLoadingDetails("studioForge");

    expect(loading.label).toBe("Studio Forge");
    expect(loading.detail).toMatch(/runtime preview cards/i);
  });

  it("preloads likely next routes for workspace flow", () => {
    expect(getPagesToPreload("workspace")).toEqual([
      "timeline",
      "render",
      "directorLab",
      "plannerLab",
      "reactiveLab",
    ]);
  });

  it("preloads setup and render-adjacent pages for Studio Forge", () => {
    expect(getPagesToPreload("studioForge")).toEqual([
      "setup",
      "models",
      "render",
    ]);
  });

  it("treats preload imports as best-effort", async () => {
    const loader = vi.fn(async () => {
      throw new Error("teardown import race");
    });

    await expect(runBestEffortPagePreload(loader)).resolves.toBeUndefined();
    expect(loader).toHaveBeenCalledTimes(1);
  });
});
