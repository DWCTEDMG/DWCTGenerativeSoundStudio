export type StudioForgeCapability =
  | "backend"
  | "systemReady"
  | "ollama"
  | "openaiCompatible"
  | "comfyui"
  | "comfyMotion"
  | "ffmpeg"
  | "internalRenderer"
  | "internalMotion"
  | "cuda"
  | "hostedRenderer"
  | "edmgCore";

export type StudioForgePrerequisite =
  | "project"
  | "audio"
  | "analysis"
  | "plan"
  | "renderOutput"
  | "deforumExport"
  | "unrealBundle";

export type StudioForgeDestination =
  | "workspace"
  | "timeline"
  | "render"
  | "queue"
  | "review"
  | "outputs"
  | "settings"
  | "setup"
  | "models";

export type StudioForgeAction = {
  label: string;
  destination: StudioForgeDestination;
};

export type StudioForgeRecipeStage = {
  id: string;
  label: string;
  description: string;
  destination: StudioForgeDestination;
  requiredCapabilities?: StudioForgeCapability[];
  anyCapabilities?: StudioForgeCapability[];
  requiredPrerequisites?: StudioForgePrerequisite[];
};

export type StudioForgeBridgeKind =
  | "metadataExport"
  | "renderHandoff"
  | "controlBridge";

export type StudioForgeBridgeTransport =
  | "fileExport"
  | "http"
  | "websocket"
  | "osc"
  | "remoteControl";

export type StudioForgeTemplateKind =
  | "page"
  | "panel"
  | "workflow"
  | "renderPreset"
  | "modelProfile";

export type StudioForgeTemplate = {
  id: string;
  name: string;
  kind: StudioForgeTemplateKind;
  description: string;
  requiredCapabilities: StudioForgeCapability[];
  optionalCapabilities?: StudioForgeCapability[];
  requiredPrerequisites?: StudioForgePrerequisite[];
  action: StudioForgeAction;
  destructive: false;
  status: "supported" | "preview";
};

export type StudioForgeRecipe = {
  id: string;
  name: string;
  description: string;
  stages: StudioForgeRecipeStage[];
  requiredCapabilities: StudioForgeCapability[];
  optionalCapabilities?: StudioForgeCapability[];
  requiredPrerequisites?: StudioForgePrerequisite[];
  action: StudioForgeAction;
  destructive: false;
  status: "supported" | "preview";
};

export type StudioForgeBridge = {
  id: string;
  name: string;
  kind: StudioForgeBridgeKind;
  description: string;
  transports: StudioForgeBridgeTransport[];
  outputs: string[];
  previewPayload: Record<string, unknown>;
  limitations: string;
  requiredCapabilities: StudioForgeCapability[];
  optionalCapabilities?: StudioForgeCapability[];
  requiredPrerequisites?: StudioForgePrerequisite[];
  action: StudioForgeAction;
  destructive: false;
  status: "supported" | "preview";
};
