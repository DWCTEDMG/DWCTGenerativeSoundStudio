const { contextBridge, ipcRenderer, shell } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

function readRuntimeDefaults() {
  const candidates = [];
  if (process.resourcesPath) {
    candidates.push(path.join(process.resourcesPath, "runtime-defaults.json"));
  }
  candidates.push(path.join(__dirname, "electron-resources", "runtime-defaults.json"));

  for (const candidate of candidates) {
    try {
      if (!fs.existsSync(candidate)) continue;
      const parsed = JSON.parse(fs.readFileSync(candidate, "utf8"));
      if (parsed && typeof parsed === "object") {
        return parsed;
      }
    } catch {}
  }

  return {};
}

const runtimeDefaults = readRuntimeDefaults();
const runtimeBackendDefaults =
  runtimeDefaults.backend && typeof runtimeDefaults.backend === "object"
    ? runtimeDefaults.backend
    : {};
const runtimeBackendHost =
  typeof runtimeBackendDefaults.host === "string" ? runtimeBackendDefaults.host.trim() : "";
const runtimeBackendPort =
  runtimeBackendDefaults.port != null ? String(runtimeBackendDefaults.port).trim() : "";
const runtimeBackendUrl =
  typeof runtimeBackendDefaults.url === "string" ? runtimeBackendDefaults.url.trim() : "";

function getArgValue(prefix) {
  const found = process.argv.find((entry) => typeof entry === "string" && entry.startsWith(prefix));
  return found ? found.slice(prefix.length) : "";
}

const BACKEND_HOST =
  process.env.EDMG_STUDIO_BACKEND_HOST ||
  getArgValue("--edmg-backend-host=") ||
  runtimeBackendHost ||
  "127.0.0.1";

const BACKEND_PORT =
  process.env.EDMG_STUDIO_BACKEND_PORT ||
  getArgValue("--edmg-backend-port=") ||
  runtimeBackendPort ||
  "7863";

const BACKEND_URL =
  process.env.EDMG_STUDIO_BACKEND_URL ||
  getArgValue("--edmg-backend-url=") ||
  runtimeBackendUrl ||
  "";

const TEST_MODE =
  (process.env.EDMG_STUDIO_TEST_MODE ?? "0") === "1" ||
  getArgValue("--edmg-test-mode=") === "1";

const DEFAULT_BACKEND_URL = BACKEND_URL || `http://${BACKEND_HOST}:${BACKEND_PORT}`;

contextBridge.exposeInMainWorld("edmg", {
  backendUrl: () => DEFAULT_BACKEND_URL,

  getBackendUrl: async () => {
    try {
      const url = await ipcRenderer.invoke("edmg:getBackendUrl");
      if (typeof url === "string" && url.trim()) {
        return url;
      }
    } catch {}

    return DEFAULT_BACKEND_URL;
  },
  getBackendSettings: () => ipcRenderer.invoke("edmg:getBackendSettings"),
  getDirectorStatus: () => ipcRenderer.invoke("edmg:getDirectorStatus"),
  setBackendSettings: (settings) => ipcRenderer.invoke("edmg:setBackendSettings", settings),

  openExternal: (url) => shell.openExternal(String(url)),
  openPath: (targetPath) => ipcRenderer.invoke("edmg:openPath", targetPath),
  showItemInFolder: (targetPath) => ipcRenderer.invoke("edmg:revealPath", targetPath),
  revealPath: (targetPath) => ipcRenderer.invoke("edmg:revealPath", targetPath),
  pickFile: (options) => ipcRenderer.invoke("edmg:pickFile", options),
  pickDirectory: (options) => ipcRenderer.invoke("edmg:pickDirectory", options),
  getStudioPaths: () => ipcRenderer.invoke("edmg:getStudioPaths"),
  getAiSettings: () => ipcRenderer.invoke("edmg:getAiSettings"),
  setStudioHome: (targetPath) => ipcRenderer.invoke("edmg:setStudioHome", targetPath),
  setStorageSettings: (settings) => ipcRenderer.invoke("edmg:setStorageSettings", settings),
  setAiSettings: (settings) => ipcRenderer.invoke("edmg:setAiSettings", settings),
  relaunch: () => ipcRenderer.invoke("edmg:relaunch"),
});

if (TEST_MODE) {
  contextBridge.exposeInMainWorld("__edmgTest", {
    writeReport: (payload) => ipcRenderer.invoke("edmg:testWriteReport", payload),
  });
}
