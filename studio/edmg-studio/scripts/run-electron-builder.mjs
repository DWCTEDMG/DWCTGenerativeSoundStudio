import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

import { writeReleaseEvidence } from "./release-evidence-lib.mjs";
import { resolveWindowsSigningPlan } from "./windows-signing-lib.mjs";

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

function existingFiles(paths) {
  return paths.filter((filePath) => fs.existsSync(filePath) && fs.statSync(filePath).isFile());
}

function stagedOwnedExecutables() {
  const backendRoot = path.join(root, "release", "staged-app", "electron-resources", "backend");
  return existingFiles([
    path.join(backendRoot, "edmg-studio-backend.exe"),
    path.join(backendRoot, "edmg-hf-bucket-helper.exe"),
  ]);
}

function packagedOwnedExecutables() {
  const unpackedRoot = path.join(root, "dist", "win-unpacked");
  const backendRoot = path.join(unpackedRoot, "resources", "backend");
  const artifacts = existingFiles([
    path.join(unpackedRoot, "EDMG Studio.exe"),
    path.join(backendRoot, "edmg-studio-backend.exe"),
    path.join(backendRoot, "edmg-hf-bucket-helper.exe"),
  ]);
  const distDir = path.join(root, "dist");
  if (fs.existsSync(distDir) && fs.statSync(distDir).isDirectory()) {
    artifacts.push(
      ...fs
        .readdirSync(distDir, { withFileTypes: true })
        .filter((entry) => entry.isFile() && /\.(?:exe|msi)$/i.test(entry.name))
        .map((entry) => path.join(distDir, entry.name)),
    );
  }
  return [...new Set(artifacts)];
}

function invokeWindowsSigning(artifactPaths, signingPlan, childEnv, phase, { verifyOnly = false } = {}) {
  if (!signingPlan.windowsTarget) return;
  const signScript = path.join(root, "packaging", "windows", "sign_release.ps1");
  if (!fs.existsSync(signScript)) {
    throw new Error(`Windows signing script is missing: ${signScript}`);
  }
  if (!artifactPaths.length && signingPlan.required) {
    throw new Error(`Required Windows signing phase ${phase} found no EDMG-owned executable artifacts.`);
  }

  for (const artifactPath of artifactPaths) {
    const args = [
      "-NoProfile",
      "-NonInteractive",
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      signScript,
      "-StudioDir",
      root,
      "-ArtifactPaths",
      artifactPath,
    ];
    if (signingPlan.required) args.push("-RequireSigning");
    if (verifyOnly) args.push("-VerifyOnly");
    const result = spawnSync("powershell.exe", args, {
      cwd: root,
      stdio: "inherit",
      shell: false,
      env: childEnv,
    });
    if (result.error) throw new Error(`Windows ${phase} signing failed: ${result.error.message}`);
    if (result.status !== 0) {
      throw new Error(`Windows ${phase} signing failed with exit code ${result.status ?? "unknown"}.`);
    }
  }
}

async function main() {
  const requestedBuilderArgs = process.argv.slice(2);
  const signingPlan = resolveWindowsSigningPlan({
    root,
    builderArgs: requestedBuilderArgs,
    env: process.env,
    platform: process.platform,
  });
  const builderArgs = signingPlan.builderArgs;
  const childEnv = {
    ...signingPlan.childEnv,
    ELECTRON_CACHE: electronCache,
    ELECTRON_BUILDER_CACHE: electronBuilderCache,
  };

  invokeWindowsSigning(stagedOwnedExecutables(), signingPlan, childEnv, "pre-pack");
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

  invokeWindowsSigning(packagedOwnedExecutables(), signingPlan, childEnv, "post-pack", { verifyOnly: true });

  const wantsWindows = requestedBuilderArgs.some((arg) => /^-w(?:$|in)|^--win/i.test(arg));
  const wantsLinux = requestedBuilderArgs.some((arg) => /^-l(?:$|inux)|^--linux/i.test(arg));
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
