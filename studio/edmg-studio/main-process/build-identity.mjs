import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";

function readManifest(candidate, fileSystem = fs) {
  try {
    if (!fileSystem.existsSync(candidate)) return null;
    const payload = JSON.parse(fileSystem.readFileSync(candidate, "utf8"));
    return payload && typeof payload === "object" && !Array.isArray(payload)
      ? { manifestPath: candidate, payload }
      : null;
  } catch {
    return null;
  }
}

function cleanText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function executablePathForApp(app) {
  try {
    return typeof app?.getPath === "function" ? cleanText(app.getPath("exe")) : "";
  } catch {
    return "";
  }
}

function cleanCount(value) {
  return Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function cleanPositiveCount(value) {
  return Number.isSafeInteger(value) && value > 0 ? value : null;
}

function isSha256(value) {
  return /^[a-f0-9]{64}$/i.test(value);
}

function backendEntryPointForPlatform(platform) {
  if (platform === "win32") return "edmg-studio-backend.exe";
  if (platform === "linux") return "edmg-studio-backend";
  return "";
}

function verifyManifestBinary({ manifest, manifestPath, platform, fileSystem = fs }) {
  const expectedEntryPoint = backendEntryPointForPlatform(platform);
  const entryPoint = cleanText(manifest?.backendEntryPoint);
  const binarySize = cleanPositiveCount(manifest?.binarySize);
  const binarySha256 = cleanText(manifest?.binarySha256).toLowerCase();
  if (
    !expectedEntryPoint ||
    cleanText(manifest?.platform) !== platform ||
    entryPoint !== expectedEntryPoint ||
    binarySize === null ||
    !isSha256(binarySha256)
  ) {
    return false;
  }

  try {
    const binaryPath = path.join(path.dirname(manifestPath), entryPoint);
    const stat = fileSystem.statSync(binaryPath);
    if (!stat.isFile() || stat.size !== binarySize) return false;
    const installedSha256 = createHash("sha256")
      .update(fileSystem.readFileSync(binaryPath))
      .digest("hex");
    return installedSha256 === binarySha256;
  } catch {
    return false;
  }
}

export function buildIdentity({
  app,
  resourcesPath = process.resourcesPath,
  rootDir,
  platform = process.platform,
  arch = process.arch,
  electronVersion = process.versions.electron || "",
  fileSystem = fs,
} = {}) {
  if (!app || typeof app.getVersion !== "function") {
    throw new TypeError("buildIdentity requires an Electron app with getVersion()");
  }

  const candidates = [];
  if (app.isPackaged === true && resourcesPath) {
    candidates.push(path.join(resourcesPath, "backend", "backend-bundle-manifest.json"));
  }
  if (app.isPackaged === true && rootDir) {
    candidates.push(path.join(rootDir, "electron-resources", "backend", "backend-bundle-manifest.json"));
  }

  const manifestRecord = candidates
    .map((candidate) => readManifest(candidate, fileSystem))
    .find((record) => record !== null) ?? null;
  const manifest = manifestRecord?.payload ?? null;

  const sourceHash = cleanText(manifest?.sourceHash);
  const lockSha256 = cleanText(manifest?.lockSha256);
  const binarySha256 = cleanText(manifest?.binarySha256);
  const manifestAvailable = Boolean(
    manifest?.ok === true &&
    cleanPositiveCount(manifest?.schemaVersion) !== null &&
    isSha256(sourceHash) &&
    isSha256(lockSha256) &&
    isSha256(binarySha256) &&
    verifyManifestBinary({
      manifest,
      manifestPath: manifestRecord?.manifestPath,
      platform: cleanText(platform),
      fileSystem,
    }),
  );

  return {
    ok: true,
    desktop: {
      version: cleanText(app.getVersion()),
      packaged: app.isPackaged === true,
      platform: cleanText(platform),
      arch: cleanText(arch),
      electronVersion: cleanText(electronVersion),
      executablePath: executablePathForApp(app),
    },
    backendBundle: {
      available: manifestAvailable,
      binaryVerified: manifestAvailable,
      schemaVersion: cleanPositiveCount(manifest?.schemaVersion),
      builder: cleanText(manifest?.builder),
      platform: cleanText(manifest?.platform),
      backendEntryPoint: cleanText(manifest?.backendEntryPoint),
      acceleratorProfile: cleanText(manifest?.acceleratorProfile),
      pythonVersion: cleanText(manifest?.pythonVersion),
      sourceHash: isSha256(sourceHash) ? sourceHash.toLowerCase() : "",
      sourceFileCount: cleanCount(manifest?.sourceFileCount),
      lockSha256: isSha256(lockSha256) ? lockSha256.toLowerCase() : "",
      binarySha256: isSha256(binarySha256) ? binarySha256.toLowerCase() : "",
    },
  };
}
