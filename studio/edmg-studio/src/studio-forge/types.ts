export type StudioForgeCapability =
  | "backend"
  | "ollama"
  | "openaiCompatible"
  | "comfyui"
  | "ffmpeg"
  | "internalRenderer"
  | "edmgCore";

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

export type StudioForgeBridge = {
  id: string;
  name: string;
  kind: StudioForgeBridgeKind;
  description: string;
  transports: StudioForgeBridgeTransport[];
  outputs: string[];
  limitations: string;
  requiredCapabilities: StudioForgeCapability[];
  optionalCapabilities?: StudioForgeCapability[];
  destructive: false;
  status: "preview";
};
