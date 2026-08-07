import path from "node:path";

import { buildCacheEnvPaths } from "../main-process/storage-env.mjs";

export const INSTALLED_APP_DIR_ENV = "EDMG_STUDIO_INSTALLED_APP_DIR";
export const TEST_BOOTSTRAP_CONFIG_PATH_ENV = "EDMG_STUDIO_TEST_BOOTSTRAP_CONFIG_PATH";

export function buildStudioProofPaths(studioHome) {
  const resolvedHome = path.resolve(studioHome);
  return {
    studioHome: resolvedHome,
    dataDir: path.join(resolvedHome, "data"),
    modelsDir: path.join(resolvedHome, "models"),
    cacheRoot: path.join(resolvedHome, "cache"),
    logsDir: path.join(resolvedHome, "logs"),
    externalDir: path.join(resolvedHome, "external"),
  };
}

export function resolveHermeticProofProfile(studioHome) {
  const profileRoot = path.join(path.resolve(studioHome), "proof-os-profile");
  const appDataDir = path.join(profileRoot, "AppData", "Roaming");
  const localAppDataDir = path.join(profileRoot, "AppData", "Local");
  const bootstrapDir = path.join(appDataDir, "EDMG Studio");
  return {
    profileRoot,
    appDataDir,
    localAppDataDir,
    bootstrapDir,
    bootstrapPath: path.join(bootstrapDir, "bootstrap.json"),
  };
}

export function buildHermeticPackagedProofEnv({
  baseEnv = process.env,
  studioHome,
  port,
  testPage,
  extraEnv = {},
} = {}) {
  const numericPort = Number(port);
  if (!Number.isInteger(numericPort) || numericPort < 1 || numericPort > 65535) {
    throw new Error(`Proof backend port must be an integer from 1 through 65535; received ${port}`);
  }
  if (!studioHome || !testPage) {
    throw new Error("A proof Studio home and test page are required");
  }

  const paths = buildStudioProofPaths(studioHome);
  const profile = resolveHermeticProofProfile(paths.studioHome);
  const backendUrl = `http://127.0.0.1:${numericPort}`;
  const environment = {
    ...baseEnv,
    EDMG_AI_MODE: "local",
    EDMG_AI_PROVIDER: "rule_based",
    ...extraEnv,
    APPDATA: profile.appDataDir,
    LOCALAPPDATA: profile.localAppDataDir,
    EDMG_STUDIO_HOME: paths.studioHome,
    EDMG_STUDIO_DATA_DIR: paths.dataDir,
    EDMG_STUDIO_MODELS_DIR: paths.modelsDir,
    EDMG_STUDIO_LOGS_DIR: paths.logsDir,
    EDMG_STUDIO_EXTERNAL_DIR: paths.externalDir,
    OLLAMA_MODELS: path.join(paths.modelsDir, "ollama"),
    ...buildCacheEnvPaths(paths.cacheRoot),
    EDMG_STUDIO_BACKEND_MODE: "managed",
    EDMG_STUDIO_SPAWN_BACKEND: "1",
    EDMG_STUDIO_BACKEND_HOST: "127.0.0.1",
    EDMG_STUDIO_BACKEND_PORT: String(numericPort),
    EDMG_STUDIO_BACKEND_URL: backendUrl,
    EDMG_BACKEND_AUTH_TOKEN: "",
    EDMG_STUDIO_BACKEND_AUTH_TOKEN: "",
    EDMG_DIRECTOR_SPAWN: "0",
    EDMG_DIRECTOR_BASE_URL: "http://127.0.0.1:9",
    EDMG_STUDIO_TEST_MODE: "1",
    EDMG_STUDIO_TEST_SKIP_MIGRATION: "0",
    [TEST_BOOTSTRAP_CONFIG_PATH_ENV]: profile.bootstrapPath,
    EDMG_STUDIO_TEST_PAGE: path.resolve(testPage),
    EDMG_STUDIO_TEST_FAKE_PATH_ACTIONS: "1",
    ELECTRON_DISABLE_SECURITY_WARNINGS: "1",
    NO_PROXY: "127.0.0.1,localhost,::1",
    no_proxy: "127.0.0.1,localhost,::1",
  };
  delete environment[INSTALLED_APP_DIR_ENV];
  return environment;
}
