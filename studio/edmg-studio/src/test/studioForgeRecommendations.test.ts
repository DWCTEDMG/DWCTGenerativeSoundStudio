import { describe, expect, it } from "vitest";
import { buildStudioForgeRecommendations } from "../studio-forge/recommendations";
import type { StudioForgeRecipe } from "../studio-forge/types";

const RECIPE: StudioForgeRecipe = {
  id: "local-render",
  name: "Local render",
  description: "Render a planned project locally.",
  stages: [],
  requiredCapabilities: ["backend", "internalRenderer"],
  optionalCapabilities: ["cuda"],
  requiredPrerequisites: ["project", "plan"],
  action: { label: "Open Render", destination: "render" },
  destructive: false,
  status: "supported",
};

describe("Studio Forge recommendations", () => {
  it("requires both runtime capabilities and saved project state", () => {
    const [recommendation] = buildStudioForgeRecommendations({
      bridges: [],
      templates: [],
      recipes: [RECIPE],
      availableCapabilities: ["backend", "internalRenderer"],
      availablePrerequisites: ["project"],
    });

    expect(recommendation.status).toBe("blocked");
    expect(recommendation.missingRequired).toEqual([]);
    expect(recommendation.missingPrerequisites).toEqual(["plan"]);
    expect(recommendation.action).toEqual({ label: "Open Render", destination: "render" });
  });

  it("reports optional acceleration separately from required readiness", () => {
    const [recommendation] = buildStudioForgeRecommendations({
      bridges: [],
      templates: [],
      recipes: [RECIPE],
      availableCapabilities: ["backend", "internalRenderer"],
      availablePrerequisites: ["project", "plan"],
    });

    expect(recommendation.status).toBe("optionalBoost");
    expect(recommendation.missingOptional).toEqual(["cuda"]);
  });
});
