export type StudioForgeCapability =
  | "backend"
  | "ollama"
  | "openaiCompatible"
  | "comfyui"
  | "ffmpeg"
  | "internalRenderer"
  | "edmgCore";

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
  destructive: false;
  status: "preview";
};

export type StudioForgeRecipe = {
  id: string;
  name: string;
  description: string;
  stages: string[];
  requiredCapabilities: StudioForgeCapability[];
  optionalCapabilities?: StudioForgeCapability[];
  destructive: false;
  status: "preview";
};
