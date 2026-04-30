import type {
  StudioForgeCapability,
  StudioForgeRecipe,
  StudioForgeTemplate,
  StudioForgeTemplateKind,
} from "./types";

export type StudioForgeRecommendationStatus = "ready" | "optionalBoost" | "blocked";

export type StudioForgeRecommendation = {
  id: string;
  name: string;
  description: string;
  source: "template" | "recipe";
  kindLabel: string;
  status: StudioForgeRecommendationStatus;
  missingRequired: StudioForgeCapability[];
  missingOptional: StudioForgeCapability[];
};

type StudioForgeRecommendationTarget = {
  id: string;
  name: string;
  description: string;
  source: "template" | "recipe";
  kindLabel: string;
  requiredCapabilities: StudioForgeCapability[];
  optionalCapabilities: StudioForgeCapability[];
};

function templateKindLabel(kind: StudioForgeTemplateKind): string {
  return {
    page: "Page template",
    panel: "Panel template",
    workflow: "Workflow template",
    renderPreset: "Render preset",
    modelProfile: "Model profile",
  }[kind];
}

function sortCapabilities(capabilities: StudioForgeCapability[]) {
  return [...capabilities].sort((left, right) => left.localeCompare(right));
}

function evaluateTarget(
  target: StudioForgeRecommendationTarget,
  availableCapabilitySet: Set<StudioForgeCapability>,
): StudioForgeRecommendation {
  const missingRequired = sortCapabilities(
    target.requiredCapabilities.filter((capability) => !availableCapabilitySet.has(capability)),
  );
  const missingOptional = sortCapabilities(
    target.optionalCapabilities.filter((capability) => !availableCapabilitySet.has(capability)),
  );
  const status: StudioForgeRecommendationStatus = missingRequired.length
    ? "blocked"
    : missingOptional.length
      ? "optionalBoost"
      : "ready";
  return {
    id: target.id,
    name: target.name,
    description: target.description,
    source: target.source,
    kindLabel: target.kindLabel,
    status,
    missingRequired,
    missingOptional,
  };
}

function statusRank(status: StudioForgeRecommendationStatus): number {
  if (status === "ready") return 0;
  if (status === "optionalBoost") return 1;
  return 2;
}

export function buildStudioForgeRecommendations({
  templates,
  recipes,
  availableCapabilities,
}: {
  templates: StudioForgeTemplate[];
  recipes: StudioForgeRecipe[];
  availableCapabilities: StudioForgeCapability[];
}): StudioForgeRecommendation[] {
  const availableCapabilitySet = new Set(availableCapabilities);
  const targets: StudioForgeRecommendationTarget[] = [
    ...templates.map((template) => ({
      id: template.id,
      name: template.name,
      description: template.description,
      source: "template" as const,
      kindLabel: templateKindLabel(template.kind),
      requiredCapabilities: template.requiredCapabilities,
      optionalCapabilities: template.optionalCapabilities ?? [],
    })),
    ...recipes.map((recipe) => ({
      id: recipe.id,
      name: recipe.name,
      description: recipe.description,
      source: "recipe" as const,
      kindLabel: "Workflow recipe",
      requiredCapabilities: recipe.requiredCapabilities,
      optionalCapabilities: recipe.optionalCapabilities ?? [],
    })),
  ];

  return targets
    .map((target) => evaluateTarget(target, availableCapabilitySet))
    .sort((left, right) => {
      const statusDiff = statusRank(left.status) - statusRank(right.status);
      if (statusDiff) return statusDiff;
      const requiredDiff = left.missingRequired.length - right.missingRequired.length;
      if (requiredDiff) return requiredDiff;
      const optionalDiff = left.missingOptional.length - right.missingOptional.length;
      if (optionalDiff) return optionalDiff;
      return left.name.localeCompare(right.name);
    });
}
