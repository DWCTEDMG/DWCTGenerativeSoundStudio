import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

import { writeReleaseEvidence } from "./release-evidence-lib.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const require = createRequire(import.meta.url);
const cacheRoot = process.env.EDMG_STUDIO_BUILD_CACHE_ROOT || path.join(root, ".cache");
const electronCache = path.join(cacheRoot, "electron");
const electronBuilderCache = path.join(cacheRoot, "electron-builder");

fs.mkdirSync(electronCache, { recursive: true });
fs.mkdirSync(electronBuilderCache, { recursive: true });

const builderEntry = require.resolve("electron-builder/cli.js");

if (!fs.existsSync(builderEntry)) {
  throw new Error(`electron-builder entry point not found: ${builderEntry}`);
}

const childEnv = {
  ...process.env,
  ELECTRON_CACHE: electronCache,
  ELECTRON_BUILDER_CACHE: electronBuilderCache,
};

function resolveEvidenceProfile() {
  const configured = String(process.env.EDMG_BACKEND_ACCELERATOR_PROFILE || "").trim();
  if (configured) return configured;

  for (const manifestPath of [
    path.join(root, "release", "staged-app", "electron-resources", "backend", "backend-bundle-manifest.json"),
    path.join(root, "electron-resources", "backend", "backend-bundle-manifest.json"),
  ]) {
    if (!fs.existsSync(manifestPath)) continue;
    const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
    const profile = String(manifest.acceleratorProfile || "").trim();
    if (profile) return profile;
  }
  return "";
}

async function main() {
  const builderArgs = process.argv.slice(2);
  const result = spawnSync(process.execPath, [builderEntry, ...builderArgs], {
    cwd: root,
    stdio: "inherit",
    shell: false,
    env: childEnv,
  });

  if (result.error) {
    throw result.error;
  }

  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }

  const wantsWindows = builderArgs.some((arg) => /^-w(?:$|in)|^--win/i.test(arg));
  const wantsLinux = builderArgs.some((arg) => /^-l(?:$|inux)|^--linux/i.test(arg));
  const wantsInstallerArtifacts = wantsWindows || wantsLinux;
  if (!wantsInstallerArtifacts) {
    return;
  }
  if (wantsWindows && wantsLinux) {
    throw new Error("Release evidence requires one Electron Builder target at a time (Windows or Linux).");
  }
  const artifactSet = wantsWindows ? "win-nsis" : "linux-appimage";

  const packageJson = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
  const evidence = await writeReleaseEvidence({
    root,
    phase: "dist",
    profile: resolveEvidenceProfile(),
    artifactSet,
    version: String(packageJson.version || ""),
    env: process.env,
  });
  console.log(
    `[run-electron-builder] release evidence written: ${path.relative(root, evidence.indexPath).split(path.sep).join("/")}`,
  );
}

main().catch((error) => {
  console.error("[run-electron-builder] release evidence generation failed", error);
  process.exit(1);
});
