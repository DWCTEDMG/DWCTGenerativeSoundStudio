import type {
  StudioForgeBridge,
  StudioForgeBridgeKind,
  StudioForgeCapability,
  StudioForgeRecipe,
  StudioForgeTemplate,
  StudioForgeTemplateKind,
  StudioForgePrerequisite,
  StudioForgeAction,
} from "./types";

export type StudioForgeRecommendationStatus = "ready" | "optionalBoost" | "blocked";

export type StudioForgeRecommendation = {
  id: string;
  name: string;
  description: string;
  source: "template" | "recipe" | "bridge";
  kindLabel: string;
  status: StudioForgeRecommendationStatus;
  missingRequired: StudioForgeCapability[];
  missingOptional: StudioForgeCapability[];
  missingPrerequisites: StudioForgePrerequisite[];
  action: StudioForgeAction;
};

type StudioForgeRecommendationTarget = {
  id: string;
  name: string;
  description: string;
  source: "template" | "recipe" | "bridge";
  kindLabel: string;
  requiredCapabilities: StudioForgeCapability[];
  optionalCapabilities: StudioForgeCapability[];
  requiredPrerequisites: StudioForgePrerequisite[];
  action: StudioForgeAction;
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

function bridgeKindLabel(kind: StudioForgeBridgeKind): string {
  return {
    metadataExport: "Bridge metadata export",
    renderHandoff: "Bridge render handoff",
    controlBridge: "Bridge control path",
  }[kind];
}

function sortCapabilities(capabilities: StudioForgeCapability[]) {
  return [...capabilities].sort((left, right) => left.localeCompare(right));
}

function evaluateTarget(
  target: StudioForgeRecommendationTarget,
  availableCapabilitySet: Set<StudioForgeCapability>,
  availablePrerequisiteSet: Set<StudioForgePrerequisite>,
): StudioForgeRecommendation {
  const missingRequired = sortCapabilities(
    target.requiredCapabilities.filter((capability) => !availableCapabilitySet.has(capability)),
  );
  const missingOptional = sortCapabilities(
    target.optionalCapabilities.filter((capability) => !availableCapabilitySet.has(capability)),
  );
  const missingPrerequisites = [...target.requiredPrerequisites]
    .filter((prerequisite) => !availablePrerequisiteSet.has(prerequisite))
    .sort((left, right) => left.localeCompare(right));
  const status: StudioForgeRecommendationStatus = missingRequired.length || missingPrerequisites.length
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
    missingPrerequisites,
    action: target.action,
  };
}

function statusRank(status: StudioForgeRecommendationStatus): number {
  if (status === "ready") return 0;
  if (status === "optionalBoost") return 1;
  return 2;
}

export function buildStudioForgeRecommendations({
  bridges,
  templates,
  recipes,
  availableCapabilities,
  availablePrerequisites = [],
}: {
  bridges: StudioForgeBridge[];
  templates: StudioForgeTemplate[];
  recipes: StudioForgeRecipe[];
  availableCapabilities: StudioForgeCapability[];
  availablePrerequisites?: StudioForgePrerequisite[];
}): StudioForgeRecommendation[] {
  const availableCapabilitySet = new Set(availableCapabilities);
  const availablePrerequisiteSet = new Set(availablePrerequisites);
  const targets: StudioForgeRecommendationTarget[] = [
    ...templates.map((template) => ({
      id: template.id,
      name: template.name,
      description: template.description,
      source: "template" as const,
      kindLabel: templateKindLabel(template.kind),
      requiredCapabilities: template.requiredCapabilities,
      optionalCapabilities: template.optionalCapabilities ?? [],
      requiredPrerequisites: template.requiredPrerequisites ?? [],
      action: template.action,
    })),
    ...recipes.map((recipe) => ({
      id: recipe.id,
      name: recipe.name,
      description: recipe.description,
      source: "recipe" as const,
      kindLabel: "Workflow recipe",
      requiredCapabilities: recipe.requiredCapabilities,
      optionalCapabilities: recipe.optionalCapabilities ?? [],
      requiredPrerequisites: recipe.requiredPrerequisites ?? [],
      action: recipe.action,
    })),
    ...bridges.map((bridge) => ({
      id: bridge.id,
      name: bridge.name,
      description: bridge.description,
      source: "bridge" as const,
      kindLabel: bridgeKindLabel(bridge.kind),
      requiredCapabilities: bridge.requiredCapabilities,
      optionalCapabilities: bridge.optionalCapabilities ?? [],
      requiredPrerequisites: bridge.requiredPrerequisites ?? [],
      action: bridge.action,
    })),
  ];

  return targets
    .map((target) => evaluateTarget(target, availableCapabilitySet, availablePrerequisiteSet))
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
