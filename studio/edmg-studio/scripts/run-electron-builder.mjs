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
const stagedBackendManifestRelativePath = path.join(
  "release",
  "staged-app",
  "electron-resources",
  "backend",
  "backend-bundle-manifest.json",
);

const WINDOWS_TARGET_FLAGS = new Set(["-w", "--win", "--windows"]);
const LINUX_TARGET_FLAGS = new Set(["-l", "--linux"]);

function normalizedFlagName(value) {
  const normalized = String(value ?? "").trim().toLowerCase();
  const assignmentIndex = normalized.indexOf("=");
  return assignmentIndex === -1 ? normalized : normalized.slice(0, assignmentIndex);
}

export function resolveRequestedInstallerTarget(builderArgs, platform = process.platform) {
  const flags = builderArgs.map(normalizedFlagName);
  const wantsWindows = flags.some((flag) => WINDOWS_TARGET_FLAGS.has(flag));
  const wantsLinux = flags.some((flag) => LINUX_TARGET_FLAGS.has(flag));

  if (wantsWindows && wantsLinux) {
    throw new Error("Electron Builder must target Windows or Linux, not both in one invocation.");
  }
  if (wantsWindows) {
    if (platform !== "win32") {
      throw new Error(
        `Windows Electron installers must be built on Windows (current host platform: ${platform}).`,
      );
    }
    return { platform: "win32", artifactSet: "win-nsis", signingArgs: ["--win"] };
  }
  if (wantsLinux) {
    if (platform !== "linux") {
      throw new Error(
        `Linux Electron installers must be built on Linux (current host platform: ${platform}).`,
      );
    }
    return { platform: "linux", artifactSet: "linux-appimage", signingArgs: ["--linux"] };
  }
  return null;
}

export function requireStagedBackendPlatform({
  targetPlatform,
  rootDir = root,
  manifestPath = path.join(rootDir, stagedBackendManifestRelativePath),
} = {}) {
  if (!targetPlatform) return null;

  if (!fs.existsSync(manifestPath) || !fs.statSync(manifestPath).isFile()) {
    throw new Error(
      `The staged backend manifest is required before ${targetPlatform} packaging: ${manifestPath}`,
    );
  }

  let manifest;
  try {
    manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  } catch (error) {
    throw new Error(`The staged backend manifest is not valid JSON: ${manifestPath}`, { cause: error });
  }

  const manifestPlatform = String(manifest?.platform ?? "").trim();
  if (!manifestPlatform) {
    throw new Error(`The staged backend manifest does not declare a platform: ${manifestPath}`);
  }
  if (manifestPlatform !== targetPlatform) {
    throw new Error(
      `Staged backend platform mismatch: Electron target ${targetPlatform} cannot package backend ${manifestPlatform}. ` +
        "Rebuild and stage the backend bundle on the target host.",
    );
  }
  return manifest;
}

export function withLinuxProfileArtifactName(builderArgs, { targetPlatform, acceleratorProfile } = {}) {
  if (targetPlatform !== "linux") return [...builderArgs];

  const hasArtifactName = builderArgs.some((arg) =>
    /^(?:-c|--config)\.artifactname(?:=|$)/i.test(String(arg ?? "").trim()),
  );
  if (hasArtifactName) return [...builderArgs];

  const profile = String(acceleratorProfile ?? "").trim().toLowerCase();
  if (!/^[a-z0-9][a-z0-9_-]*$/.test(profile)) {
    throw new Error("The staged Linux backend manifest must declare a filename-safe acceleratorProfile.");
  }

  return [
    ...builderArgs,
    `-c.artifactName=EDMG-Studio-\${version}-linux-x64-${profile}.\${ext}`,
  ];
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
  const releaseTarget = resolveRequestedInstallerTarget(requestedBuilderArgs, process.platform);
  const stagedBackendManifest = requireStagedBackendPlatform({ targetPlatform: releaseTarget?.platform });
  const packagingBuilderArgs = withLinuxProfileArtifactName(requestedBuilderArgs, {
    targetPlatform: releaseTarget?.platform,
    acceleratorProfile: stagedBackendManifest?.acceleratorProfile,
  });

  const cacheRoot = process.env.EDMG_STUDIO_BUILD_CACHE_ROOT || path.join(root, ".cache");
  const electronCache = path.join(cacheRoot, "electron");
  const electronBuilderCache = path.join(cacheRoot, "electron-builder");
  fs.mkdirSync(electronCache, { recursive: true });
  fs.mkdirSync(electronBuilderCache, { recursive: true });

  const builderEntry = require.resolve("electron-builder/cli.js");
  if (!fs.existsSync(builderEntry)) {
    throw new Error(`electron-builder entry point not found: ${builderEntry}`);
  }

  // Classify signing from the exact target decision above. This prevents unrelated
  // options beginning with "--win" or "--linux" from being treated as platform flags.
  const signingClassificationArgs = releaseTarget?.signingArgs ?? [];
  const resolvedSigningPlan = resolveWindowsSigningPlan({
    root,
    builderArgs: signingClassificationArgs,
    env: process.env,
    platform: process.platform,
  });
  const signingArgs = resolvedSigningPlan.builderArgs.slice(signingClassificationArgs.length);
  const signingPlan = {
    ...resolvedSigningPlan,
    builderArgs: [...packagingBuilderArgs, ...signingArgs],
  };
  const builderArgs = signingPlan.builderArgs;
  const childEnv = {
    ...signingPlan.childEnv,
    ELECTRON_CACHE: electronCache,
    ELECTRON_BUILDER_CACHE: electronBuilderCache,
    EDMG_WINDOWS_SIGNING_REQUIRED: signingPlan.required ? "1" : "0",
    EDMG_WINDOWS_SIGNING_CONFIGURED: signingPlan.configured ? "1" : "0",
  };

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

  if (!releaseTarget) {
    return;
  }

  const packageJson = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
  const evidence = await writeReleaseEvidence({
    root,
    phase: "dist",
    profile: resolveEvidenceProfile(),
    artifactSet: releaseTarget.artifactSet,
    version: String(packageJson.version || ""),
    env: process.env,
  });
  console.log(
    `[run-electron-builder] release evidence written: ${path.relative(root, evidence.indexPath).split(path.sep).join("/")}`,
  );
}

const invokedAsScript = Boolean(process.argv[1]) && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (invokedAsScript) {
  main().catch((error) => {
    console.error("[run-electron-builder] release packaging failed", error);
    process.exit(1);
  });
}
