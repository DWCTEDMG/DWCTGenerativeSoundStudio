import crypto from "node:crypto";
import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import {
  PINNED_UV_VERSION,
  RELEASE_CAPABILITY_EXTRAS,
  RELEASE_MANIFEST_SCHEMA_VERSION,
  assertNoDynamicDependencyOverrides,
  assertPinnedUvVersion,
  assertPython312,
  assertTorchIndexForProfile,
  assertTrackedCleanDependencyStatus,
  binaryMatchesManifest,
  releaseProvenanceMatches,
  resolveAcceleratorProfile,
  sha256File,
  uvLockCheckArgs,
  uvRunArgs,
  uvSyncArgs,
} from "./release-python-toolchain.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const repoRoot = path.resolve(root, "..", "..");
const pythonBackendDir = path.join(root, "python_backend");
const pythonVersionPath = path.join(repoRoot, ".python-version");
const pyprojectPath = path.join(pythonBackendDir, "pyproject.toml");
const uvLockPath = path.join(pythonBackendDir, "uv.lock");
const provenanceScriptPath = path.join(__dirname, "release_provenance.py");
const toolchainScriptPath = path.join(__dirname, "release-python-toolchain.mjs");
const electronBackendDir = path.join(root, "electron-resources", "backend");
const directorAppDir = path.resolve(root, "..", "..", "chatgpt-apps", "edmg-director");
const electronDirectorDir = path.join(root, "electron-resources", "director");
const directorBundleManifestPath = path.join(electronDirectorDir, "director-bundle-manifest.json");
const backendBinaryName = process.platform === "win32" ? "edmg-studio-backend.exe" : "edmg-studio-backend";
const bundledBackendPath = path.join(electronBackendDir, backendBinaryName);
const bundleManifestPath = path.join(electronBackendDir, "backend-bundle-manifest.json");
const pnpmCommand = process.platform === "win32" ? "pnpm.cmd" : "pnpm";

const dependencyInputPaths = [pythonVersionPath, pyprojectPath, uvLockPath];
const requiredBackendSourceFiles = [
  "edmg_studio_backend/app.py",
  "edmg_studio_backend/services/internal_video.py",
  "edmg_studio_backend/services/internal_video_models.py",
  "edmg_studio_backend/services/model_catalog.py",
  "edmg_studio_backend/services/model_manager.py",
  "edmg_studio_backend/services/tensorrt_standalone.py",
  "edmg_studio_backend/services/tensorrt_video.py",
];

function runChecked(label, command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd ?? root,
    env: options.env ?? process.env,
    stdio: "inherit",
    shell: false,
  });
  if (result.error) throw new Error(`${label} failed: ${result.error.message}`);
  if (result.status !== 0) {
    throw new Error(`${label} failed with exit code ${result.status ?? "unknown"}`);
  }
}

function runCaptured(label, command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd ?? root,
    env: options.env ?? process.env,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    shell: false,
  });
  if (result.error) throw new Error(`${label} failed: ${result.error.message}`);
  if (result.status !== 0) {
    const detail = String(result.stderr || result.stdout || "").trim();
    throw new Error(`${label} failed with exit code ${result.status ?? "unknown"}${detail ? `: ${detail}` : ""}`);
  }
  return String(result.stdout || "").trim();
}

function runPnpmChecked(label, args, options = {}) {
  const execPath = String(process.env.npm_execpath || "").trim();
  if (execPath && fs.existsSync(execPath)) {
    if (/\.(?:c?js|mjs)$/i.test(execPath)) {
      runChecked(label, process.execPath, [execPath, ...args], options);
      return;
    }
    runChecked(label, execPath, args, options);
    return;
  }
  runChecked(label, pnpmCommand, args, options);
}

function repoRelative(filePath) {
  return path.relative(repoRoot, filePath).split(path.sep).join("/");
}

function assertRequiredFiles() {
  const missing = [
    ...dependencyInputPaths,
    provenanceScriptPath,
    toolchainScriptPath,
    ...requiredBackendSourceFiles.map((relativePath) => path.join(pythonBackendDir, relativePath)),
  ].filter((filePath) => !fs.existsSync(filePath));
  if (missing.length) {
    throw new Error(`Release bundle is missing required inputs: ${missing.map(repoRelative).join(", ")}`);
  }
  const pythonPin = fs.readFileSync(pythonVersionPath, "utf8").trim();
  if (pythonPin !== "3.12") {
    throw new Error(`.python-version must contain exactly 3.12 for release builds; got ${JSON.stringify(pythonPin)}`);
  }
}

function assertTrackedCleanDependencyInputs() {
  const relativePaths = dependencyInputPaths.map(repoRelative);
  const tracked = spawnSync("git", ["ls-files", "--error-unmatch", "--", ...relativePaths], {
    cwd: repoRoot,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    shell: false,
  });
  if (tracked.error) throw new Error(`Could not verify tracked dependency inputs: ${tracked.error.message}`);
  const dirty = runCaptured(
    "check release dependency input state",
    "git",
    ["status", "--porcelain=v1", "--", ...relativePaths],
    { cwd: repoRoot },
  );
  assertTrackedCleanDependencyStatus({
    trackedStatus: tracked.status,
    dirtyStatus: dirty,
    paths: relativePaths,
  });
}

function resolveUv() {
  const uvCommand = String(process.env.EDMG_UV || "uv").trim();
  if (!uvCommand) throw new Error("EDMG_UV must not be empty");
  const versionOutput = runCaptured("query uv version", uvCommand, ["--version"], { cwd: pythonBackendDir });
  const uvVersion = assertPinnedUvVersion(versionOutput, PINNED_UV_VERSION);
  return { uvCommand, uvVersion };
}

function synchronizeReleaseEnvironment(uvCommand, profile) {
  runChecked("validate committed uv lock", uvCommand, uvLockCheckArgs(), { cwd: pythonBackendDir });
  runChecked("synchronize frozen release environment", uvCommand, uvSyncArgs(profile), { cwd: pythonBackendDir });
}

function collectReleaseProvenance(uvCommand, profile) {
  const stdout = runCaptured(
    "collect release provenance",
    uvCommand,
    uvRunArgs(profile, [
      "python",
      provenanceScriptPath,
      "--lock",
      uvLockPath,
      "--profile",
      profile,
    ]),
    { cwd: pythonBackendDir },
  );
  let payload;
  try {
    payload = JSON.parse(stdout);
  } catch {
    throw new Error(`Release provenance helper returned invalid JSON: ${stdout}`);
  }
  assertPython312(payload.pythonVersion);
  assertTorchIndexForProfile(profile, payload.torchIndex);
  if (!String(payload.pyinstallerVersion || "").trim()) throw new Error("Release provenance omitted PyInstaller version");
  if (!Array.isArray(payload.torchPackages) || payload.torchPackages.length !== 3) {
    throw new Error("Release provenance must include torch, torchvision, and torchaudio");
  }
  if (!Array.isArray(payload.nltkResources) || payload.nltkResources.length === 0) {
    throw new Error("Release provenance must include pinned NLTK resources");
  }
  return payload;
}

function trackedBackendFiles() {
  const stdout = runCaptured(
    "inventory tracked backend sources",
    "git",
    ["ls-files", "-z", "--", "studio/edmg-studio/python_backend"],
    { cwd: repoRoot },
  );
  const paths = stdout.split("\0").filter(Boolean).map((relativePath) => path.join(repoRoot, relativePath));
  if (!paths.length) throw new Error("No tracked backend source files were found");
  return paths;
}

async function computeBackendSourceFingerprint() {
  const filesByRelativePath = new Map();
  for (const filePath of [
    ...trackedBackendFiles(),
    pythonVersionPath,
    fileURLToPath(import.meta.url),
    toolchainScriptPath,
    provenanceScriptPath,
  ]) {
    if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) continue;
    filesByRelativePath.set(repoRelative(filePath), filePath);
  }

  const files = [...filesByRelativePath.entries()].sort(([left], [right]) => left.localeCompare(right));
  const hash = crypto.createHash("sha256");
  for (const [relativePath, filePath] of files) {
    hash.update(relativePath);
    hash.update("\n");
    hash.update(await fsp.readFile(filePath));
    hash.update("\n");
  }

  const fingerprintInputs = [];
  for (const filePath of dependencyInputPaths) {
    fingerprintInputs.push({ path: repoRelative(filePath), sha256: await sha256File(filePath) });
  }
  return {
    sourceHash: hash.digest("hex"),
    fileCount: files.length,
    fingerprintInputs,
    requiredSources: [...requiredBackendSourceFiles],
  };
}

function readBundleManifest() {
  if (!fs.existsSync(bundleManifestPath)) return null;
  try {
    return JSON.parse(fs.readFileSync(bundleManifestPath, "utf8"));
  } catch {
    return null;
  }
}

function distBackendCandidates() {
  return [
    path.join(pythonBackendDir, "dist", "edmg-studio-backend", backendBinaryName),
    path.join(pythonBackendDir, "dist", backendBinaryName),
  ];
}

async function reusableBundle(expected) {
  const manifest = readBundleManifest();
  if (!manifest || !releaseProvenanceMatches(manifest, expected)) return null;
  if (!(await binaryMatchesManifest(bundledBackendPath, manifest))) return null;
  return manifest;
}

function buildBackendBundle(uvCommand, profile) {
  runChecked(
    "build backend bundle with frozen uv environment",
    uvCommand,
    uvRunArgs(profile, ["pyinstaller", "pyinstaller.spec", "--clean", "--noconfirm"]),
    { cwd: pythonBackendDir },
  );
  const built = distBackendCandidates().find((candidate) => fs.existsSync(candidate));
  if (!built) {
    throw new Error(`Backend build completed but ${backendBinaryName} was not found under python_backend/dist`);
  }
  return built;
}

async function stageBackendBundle(sourcePath, expected) {
  await fsp.mkdir(electronBackendDir, { recursive: true });
  await fsp.copyFile(sourcePath, bundledBackendPath);
  const stat = await fsp.stat(bundledBackendPath);
  const manifest = {
    schemaVersion: RELEASE_MANIFEST_SCHEMA_VERSION,
    ok: true,
    builder: "scripts/prepare-release-bundle.mjs",
    sourceHash: expected.sourceHash,
    sourceFileCount: expected.sourceFileCount,
    requiredBackendSources: expected.requiredBackendSources,
    fingerprintInputs: expected.fingerprintInputs,
    lockSha256: expected.lockSha256,
    acceleratorProfile: expected.acceleratorProfile,
    capabilityExtras: expected.capabilityExtras,
    pythonVersion: expected.pythonVersion,
    pythonImplementation: expected.pythonImplementation,
    uvVersion: expected.uvVersion,
    pyinstallerVersion: expected.pyinstallerVersion,
    torchIndex: expected.torchIndex,
    torchPackages: expected.torchPackages,
    nltkResources: expected.nltkResources,
    bundledBackend: path.relative(root, bundledBackendPath).split(path.sep).join("/"),
    sourceArtifact: path.relative(root, sourcePath).split(path.sep).join("/"),
    binarySha256: await sha256File(bundledBackendPath),
    binarySize: stat.size,
    reusedExistingBuild: false,
    preparedAt: new Date().toISOString(),
  };
  await fsp.writeFile(bundleManifestPath, JSON.stringify(manifest, null, 2) + "\n", "utf8");
  return manifest;
}

async function stageDirectorBundle() {
  if (!fs.existsSync(directorAppDir)) throw new Error(`Director app directory is missing: ${directorAppDir}`);
  for (const name of ["package.json", "pnpm-lock.yaml"]) {
    if (!fs.existsSync(path.join(directorAppDir, name))) {
      throw new Error(`Director frozen dependency input is missing: ${path.join(directorAppDir, name)}`);
    }
  }

  runPnpmChecked("install frozen director dependencies", ["install", "--frozen-lockfile"], { cwd: directorAppDir });
  runPnpmChecked("build director bundle", ["run", "build"], { cwd: directorAppDir });

  const requiredEntries = [
    path.join(directorAppDir, "dist-server", "server.js"),
    path.join(directorAppDir, "assets"),
    path.join(directorAppDir, "node_modules"),
    path.join(directorAppDir, "package.json"),
  ];
  for (const entry of requiredEntries) {
    if (!fs.existsSync(entry)) throw new Error(`Director bundle build is missing required artifact: ${entry}`);
  }

  await fsp.rm(electronDirectorDir, { recursive: true, force: true });
  await fsp.mkdir(electronDirectorDir, { recursive: true });
  const copyEntries = ["assets", "dist-server", "node_modules", "package.json", "README.md"];
  for (const name of copyEntries) {
    const source = path.join(directorAppDir, name);
    if (!fs.existsSync(source)) continue;
    await fsp.cp(source, path.join(electronDirectorDir, name), {
      recursive: true,
      force: true,
      dereference: false,
    });
  }

  const manifest = {
    ok: true,
    builder: "scripts/prepare-release-bundle.mjs",
    directorAppDir: path.relative(root, directorAppDir).split(path.sep).join("/"),
    bundledDirectorDir: path.relative(root, electronDirectorDir).split(path.sep).join("/"),
    included: copyEntries.filter((name) => fs.existsSync(path.join(electronDirectorDir, name))),
    lockSha256: await sha256File(path.join(directorAppDir, "pnpm-lock.yaml")),
    preparedAt: new Date().toISOString(),
  };
  await fsp.writeFile(directorBundleManifestPath, JSON.stringify(manifest, null, 2) + "\n", "utf8");
  return manifest;
}

async function main() {
  assertNoDynamicDependencyOverrides(process.env);
  const acceleratorProfile = resolveAcceleratorProfile({ argv: process.argv.slice(2), env: process.env });
  assertRequiredFiles();
  assertTrackedCleanDependencyInputs();
  const { uvCommand, uvVersion } = resolveUv();

  runChecked("prepare electron build assets", process.execPath, [path.join(__dirname, "prepare-electron-build.mjs")], {
    cwd: root,
  });
  synchronizeReleaseEnvironment(uvCommand, acceleratorProfile);
  const provenance = collectReleaseProvenance(uvCommand, acceleratorProfile);
  const fingerprint = await computeBackendSourceFingerprint();
  const lockSha256 = await sha256File(uvLockPath);
  const expected = {
    sourceHash: fingerprint.sourceHash,
    sourceFileCount: fingerprint.fileCount,
    requiredBackendSources: fingerprint.requiredSources,
    fingerprintInputs: fingerprint.fingerprintInputs,
    lockSha256,
    acceleratorProfile,
    capabilityExtras: [...RELEASE_CAPABILITY_EXTRAS],
    uvVersion,
    ...provenance,
  };

  const existing = await reusableBundle(expected);
  if (existing) {
    const directorManifest = await stageDirectorBundle();
    console.log(JSON.stringify({
      ok: true,
      skippedRebuild: true,
      reason: "bundled backend matches the committed lock, profile, provenance, sources, and binary hash",
      bundleManifestPath,
      manifest: existing,
      directorBundleManifestPath,
      directorManifest,
    }, null, 2));
    return;
  }

  const sourceArtifact = buildBackendBundle(uvCommand, acceleratorProfile);
  const manifest = await stageBackendBundle(sourceArtifact, expected);
  const directorManifest = await stageDirectorBundle();
  console.log(JSON.stringify({ ok: true, bundleManifestPath, manifest, directorBundleManifestPath, directorManifest }, null, 2));
}

main().catch((error) => {
  console.error("[prepare-release-bundle] FAILED", error);
  process.exit(1);
});
