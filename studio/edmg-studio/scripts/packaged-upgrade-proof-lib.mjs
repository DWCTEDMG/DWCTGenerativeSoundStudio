import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export const INSTALLED_APP_DIR_ARG = "--installed-app-dir";
export const INSTALLED_APP_DIR_ENV = "EDMG_STUDIO_INSTALLED_APP_DIR";

function proofError(message) {
  return new Error(`Installed-app baseline is invalid: ${message}`);
}

function normalizedForComparison(value, platform = process.platform) {
  const normalized = path.resolve(value).replace(/[\\/]+$/, "");
  return platform === "win32" ? normalized.toLowerCase() : normalized;
}

function isSameOrDescendant(candidate, ancestor, platform = process.platform) {
  const normalizedCandidate = normalizedForComparison(candidate, platform);
  const normalizedAncestor = normalizedForComparison(ancestor, platform);
  const relative = path.relative(normalizedAncestor, normalizedCandidate);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

async function canonicalizeProspectivePath(value) {
  let existingAncestor = path.resolve(value);
  const missingSegments = [];
  while (true) {
    try {
      const realAncestor = await fsp.realpath(existingAncestor);
      return path.join(realAncestor, ...missingSegments.reverse());
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
      const parent = path.dirname(existingAncestor);
      if (parent === existingAncestor) throw error;
      missingSegments.push(path.basename(existingAncestor));
      existingAncestor = parent;
    }
  }
}

function requireSha256(value, label) {
  if (typeof value !== "string" || !/^[a-f0-9]{64}$/i.test(value)) {
    throw proofError(`${label} must be a SHA-256 digest`);
  }
  return value.toLowerCase();
}

function requireNonEmptyString(value, label) {
  if (typeof value !== "string" || value.trim() === "") {
    throw proofError(`${label} must be a non-empty string`);
  }
  return value.trim();
}

function requireSafeEntryPoint(value, expected) {
  const entryPoint = requireNonEmptyString(value, "backend manifest backendEntryPoint");
  if (entryPoint.includes("/") || entryPoint.includes("\\") || entryPoint === "." || entryPoint === "..") {
    throw proofError("backend manifest backendEntryPoint must be a file name");
  }
  if (entryPoint !== expected) {
    throw proofError(`backend manifest backendEntryPoint must be ${expected}`);
  }
  return entryPoint;
}

async function sha256File(filePath) {
  const hash = createHash("sha256");
  const stream = fs.createReadStream(filePath);
  for await (const chunk of stream) {
    hash.update(chunk);
  }
  return hash.digest("hex");
}

async function inspectRequiredFile(filePath, appDir) {
  let stat;
  try {
    stat = await fsp.stat(filePath);
  } catch (error) {
    throw proofError(`required file is missing: ${path.relative(appDir, filePath)} (${error.message})`);
  }
  if (!stat.isFile()) {
    throw proofError(`required path is not a file: ${path.relative(appDir, filePath)}`);
  }
  const realPath = await fsp.realpath(filePath);
  if (!isSameOrDescendant(realPath, appDir)) {
    throw proofError(`required file resolves outside the installed directory: ${path.relative(appDir, filePath)}`);
  }
  return {
    path: path.relative(appDir, filePath).replaceAll("\\", "/"),
    size: stat.size,
    sha256: await sha256File(filePath),
    modifiedAt: stat.mtime.toISOString(),
  };
}

async function inspectOptionalFile(filePath, appDir) {
  try {
    await fsp.access(filePath);
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw proofError(`optional installed file is unreadable: ${path.relative(appDir, filePath)} (${error.message})`);
  }
  return inspectRequiredFile(filePath, appDir);
}

async function readJsonObject(filePath, label) {
  let value;
  try {
    value = JSON.parse(await fsp.readFile(filePath, "utf8"));
  } catch (error) {
    throw proofError(`${label} is not readable JSON (${error.message})`);
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw proofError(`${label} must contain a JSON object`);
  }
  return value;
}

export function parseInstalledAppDirArg(argv = []) {
  let configured = "";
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    let value = "";
    if (argument === INSTALLED_APP_DIR_ARG) {
      value = argv[index + 1] ?? "";
      index += 1;
    } else if (argument.startsWith(`${INSTALLED_APP_DIR_ARG}=`)) {
      value = argument.slice(INSTALLED_APP_DIR_ARG.length + 1);
    } else {
      continue;
    }

    if (configured) {
      throw proofError(`${INSTALLED_APP_DIR_ARG} may only be supplied once`);
    }
    if (!value.trim()) {
      throw proofError(`${INSTALLED_APP_DIR_ARG} requires an absolute directory path`);
    }
    configured = value.trim();
  }
  return configured;
}

export function resolveInstalledAppDir({ argv = [], env = process.env } = {}) {
  const cliValue = parseInstalledAppDirArg(argv);
  const envValue = typeof env[INSTALLED_APP_DIR_ENV] === "string" ? env[INSTALLED_APP_DIR_ENV].trim() : "";
  const configured = cliValue || envValue;
  if (!configured) return "";
  if (!path.isAbsolute(configured)) {
    throw proofError(`${INSTALLED_APP_DIR_ARG}/${INSTALLED_APP_DIR_ENV} must be an absolute path: ${configured}`);
  }
  return path.normalize(configured);
}

export async function readInstalledExecutableVersion(executablePath, { platform = process.platform } = {}) {
  if (platform !== "win32") {
    return {
      fileVersion: null,
      productVersion: null,
      productName: "EDMG Studio",
      companyName: null,
    };
  }

  const systemRoot = process.env.SystemRoot || "C:\\Windows";
  const powershell = path.join(systemRoot, "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
  const script = [
    "$ErrorActionPreference='Stop'",
    "$p=[Environment]::GetEnvironmentVariable('EDMG_PROOF_VERSION_FILE')",
    "$v=(Get-Item -LiteralPath $p).VersionInfo",
    "[ordered]@{fileVersion=$v.FileVersion;productVersion=$v.ProductVersion;productName=$v.ProductName;companyName=$v.CompanyName}|ConvertTo-Json -Compress",
  ].join("; ");
  let stdout;
  try {
    ({ stdout } = await execFileAsync(powershell, [
      "-NoLogo",
      "-NoProfile",
      "-NonInteractive",
      "-Command",
      script,
    ], {
      windowsHide: true,
      env: {
        ...process.env,
        EDMG_PROOF_VERSION_FILE: executablePath,
      },
    }));
  } catch (error) {
    throw proofError(`could not read EDMG executable version metadata (${error.message})`);
  }

  try {
    return JSON.parse(stdout.trim());
  } catch (error) {
    throw proofError(`EDMG executable version metadata was not valid JSON (${error.message})`);
  }
}

export async function inspectInstalledAppBaseline(
  configuredDir,
  {
    platform = process.platform,
    versionReader = readInstalledExecutableVersion,
  } = {},
) {
  if (typeof configuredDir !== "string" || !path.isAbsolute(configuredDir)) {
    throw proofError("installed app directory must be an absolute path");
  }

  let inputStat;
  try {
    inputStat = await fsp.stat(configuredDir);
  } catch (error) {
    throw proofError(`installed app directory does not exist (${error.message})`);
  }
  if (!inputStat.isDirectory()) {
    throw proofError("installed app path must be a directory, not an executable or file");
  }

  const appDir = await fsp.realpath(configuredDir);
  const executableName = platform === "win32" ? "EDMG Studio.exe" : "EDMG Studio";
  const expectedBackendEntryPoint = platform === "win32" ? "edmg-studio-backend.exe" : "edmg-studio-backend";
  const resourcesDir = path.join(appDir, "resources");
  const backendDir = path.join(resourcesDir, "backend");
  const paths = {
    appExecutable: path.join(appDir, executableName),
    appAsar: path.join(resourcesDir, "app.asar"),
    runtimeDefaults: path.join(resourcesDir, "runtime-defaults.json"),
    backendManifest: path.join(backendDir, "backend-bundle-manifest.json"),
    backendLauncherDefaults: path.join(backendDir, "launcher_env.defaults.json"),
  };

  const backendManifest = await readJsonObject(paths.backendManifest, "backend bundle manifest");
  if (!Number.isInteger(backendManifest.schemaVersion) || backendManifest.schemaVersion < 1) {
    throw proofError("backend manifest schemaVersion must be a positive integer");
  }
  if (backendManifest.ok !== true) {
    throw proofError("backend manifest must report ok=true");
  }
  if (backendManifest.bundleLayout !== "onedir") {
    throw proofError("backend manifest must describe the supported onedir bundle layout");
  }
  const backendEntryPoint = requireSafeEntryPoint(backendManifest.backendEntryPoint, expectedBackendEntryPoint);
  const manifestBinarySha256 = requireSha256(backendManifest.binarySha256, "backend manifest binarySha256");
  if (!Number.isSafeInteger(backendManifest.binarySize) || backendManifest.binarySize <= 0) {
    throw proofError("backend manifest binarySize must be a positive integer");
  }
  const sourceHash = requireSha256(backendManifest.sourceHash, "backend manifest sourceHash");
  const acceleratorProfile = requireNonEmptyString(backendManifest.acceleratorProfile, "backend manifest acceleratorProfile");
  const pythonVersion = requireNonEmptyString(backendManifest.pythonVersion, "backend manifest pythonVersion");
  const uvVersion = requireNonEmptyString(backendManifest.uvVersion, "backend manifest uvVersion");
  const pyinstallerVersion = requireNonEmptyString(backendManifest.pyinstallerVersion, "backend manifest pyinstallerVersion");
  paths.backendExecutable = path.join(backendDir, backendEntryPoint);

  const version = await versionReader(paths.appExecutable, { platform });
  if (!version || version.productName !== "EDMG Studio") {
    throw proofError("executable ProductName must be EDMG Studio");
  }
  if (platform === "win32") {
    const fileVersion = requireNonEmptyString(version.fileVersion, "executable FileVersion");
    const productVersion = requireNonEmptyString(version.productVersion, "executable ProductVersion");
    if (compareNumericVersions(fileVersion, productVersion) !== 0) {
      throw proofError(
        `executable FileVersion ${fileVersion} does not match ProductVersion ${productVersion}`,
      );
    }
  }

  const files = {};
  for (const [label, filePath] of Object.entries(paths)) {
    files[label] = await inspectRequiredFile(filePath, appDir);
  }
  for (const [label, filePath] of [
    ["uninstallerExecutable", path.join(appDir, "unins000.exe")],
    ["uninstallerData", path.join(appDir, "unins000.dat")],
  ]) {
    const evidence = await inspectOptionalFile(filePath, appDir);
    if (evidence) files[label] = evidence;
  }
  if (files.backendExecutable.size !== backendManifest.binarySize) {
    throw proofError(
      `backend executable size does not match its manifest (${files.backendExecutable.size} != ${backendManifest.binarySize})`,
    );
  }
  if (files.backendExecutable.sha256 !== manifestBinarySha256) {
    throw proofError("backend executable SHA-256 does not match its manifest");
  }

  return {
    schemaVersion: 1,
    mode: "read-only",
    capturedAt: new Date().toISOString(),
    appDir,
    version: {
      fileVersion: version.fileVersion ?? null,
      productVersion: version.productVersion ?? null,
      productName: version.productName,
      companyName: version.companyName ?? null,
    },
    backend: {
      manifestSchemaVersion: backendManifest.schemaVersion,
      sourceHash,
      acceleratorProfile,
      pythonVersion,
      uvVersion,
      pyinstallerVersion,
      entryPoint: backendEntryPoint,
      binarySize: backendManifest.binarySize,
      binarySha256: manifestBinarySha256,
    },
    files,
  };
}

export async function inspectPackagedAppCandidate(
  candidateExecutable,
  {
    platform = process.platform,
    versionReader = readInstalledExecutableVersion,
  } = {},
) {
  if (typeof candidateExecutable !== "string" || candidateExecutable.trim() === "") {
    throw new Error("Packaged candidate executable path is required");
  }
  let realExecutable;
  try {
    realExecutable = await fsp.realpath(candidateExecutable);
  } catch (error) {
    throw new Error(`Packaged candidate executable does not exist: ${candidateExecutable} (${error.message})`);
  }
  const stat = await fsp.stat(realExecutable);
  if (!stat.isFile()) {
    throw new Error(`Packaged candidate path must be an executable file: ${candidateExecutable}`);
  }

  const evidence = await inspectInstalledAppBaseline(path.dirname(realExecutable), { platform, versionReader });
  const expectedName = platform === "win32" ? "EDMG Studio.exe" : "EDMG Studio";
  const expectedExecutable = await fsp.realpath(path.join(evidence.appDir, expectedName));
  if (normalizedForComparison(realExecutable, platform) !== normalizedForComparison(expectedExecutable, platform)) {
    throw new Error(`Packaged candidate executable must be ${expectedName}`);
  }
  return {
    ...evidence,
    mode: "candidate",
  };
}

function numericVersionParts(value, label) {
  const normalized = requireNonEmptyString(value, label);
  if (!/^\d+(?:\.\d+){0,3}$/.test(normalized)) {
    throw proofError(`${label} must contain one to four numeric components: ${normalized}`);
  }
  return normalized.split(".").map((part) => Number(part));
}

export function compareNumericVersions(left, right) {
  const leftParts = numericVersionParts(left, "left version");
  const rightParts = numericVersionParts(right, "right version");
  const width = Math.max(leftParts.length, rightParts.length);
  for (let index = 0; index < width; index += 1) {
    const difference = (leftParts[index] ?? 0) - (rightParts[index] ?? 0);
    if (difference !== 0) return difference > 0 ? 1 : -1;
  }
  return 0;
}

export function assertCandidateVersionIsNewer(installedBaseline, candidate) {
  const baselineVersion = installedBaseline?.version?.fileVersion ?? installedBaseline?.version?.productVersion;
  const candidateVersion = candidate?.version?.fileVersion ?? candidate?.version?.productVersion;
  const comparison = compareNumericVersions(candidateVersion, baselineVersion);
  if (comparison <= 0) {
    throw new Error(
      `Packaged candidate version ${candidateVersion} must be newer than installed baseline version ${baselineVersion}; `
      + "a same-build or downgrade migration is not release upgrade evidence",
    );
  }
  return {
    rule: "candidate-version-greater-than-installed-baseline",
    installedBaselineVersion: baselineVersion,
    candidateVersion,
    comparison: "newer",
    passed: true,
  };
}

export function installedBaselineFingerprint(evidence, { platform = process.platform } = {}) {
  if (!evidence || evidence.mode !== "read-only" || !evidence.appDir) {
    throw proofError("baseline evidence is missing or malformed");
  }
  return {
    appDir: normalizedForComparison(evidence.appDir, platform),
    version: evidence.version,
    backend: evidence.backend,
    files: evidence.files,
  };
}

export function assertInstalledAppBaselineUnchanged(before, after, { platform = process.platform } = {}) {
  const beforeFingerprint = JSON.stringify(installedBaselineFingerprint(before, { platform }));
  const afterFingerprint = JSON.stringify(installedBaselineFingerprint(after, { platform }));
  if (beforeFingerprint !== afterFingerprint) {
    throw new Error("Installed-app baseline changed while the packaged upgrade proof was running");
  }
}

export async function assertPathOutsideInstalledAppBaseline(
  installedAppDir,
  candidatePath,
  label,
  { platform = process.platform } = {},
) {
  if (!candidatePath) return;
  const [realInstalledAppDir, realCandidatePath] = await Promise.all([
    canonicalizeProspectivePath(installedAppDir),
    canonicalizeProspectivePath(candidatePath),
  ]);
  if (isSameOrDescendant(realCandidatePath, realInstalledAppDir, platform)) {
    throw new Error(`${label} must not be inside the read-only installed-app baseline: ${candidatePath}`);
  }
}
