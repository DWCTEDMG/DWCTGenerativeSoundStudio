import { describe, expect, it } from "vitest";
import { getPageLoadingDetails, getPagesToPreload } from "../App";

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
});
