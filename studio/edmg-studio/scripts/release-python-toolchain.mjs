import crypto from "node:crypto";
import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";

export const PINNED_UV_VERSION = "0.11.28";
export const RELEASE_MANIFEST_SCHEMA_VERSION = 2;
export const ACCELERATOR_PROFILES = Object.freeze(["cpu", "directml", "cuda"]);
export const RELEASE_CAPABILITY_EXTRAS = Object.freeze([
  "core",
  "audio",
  "asr",
  "internal-video",
  "aws",
]);

const DYNAMIC_DEPENDENCY_ENV_VARS = Object.freeze([
  "EDMG_BACKEND_BUNDLE_EXTRA",
  "EDMG_BACKEND_CUDA_BUNDLE",
  "EDMG_STUDIO_CUDA_BUNDLE",
  "EDMG_BACKEND_TORCH_INDEX_URL",
  "EDMG_CUDA_WHEEL_INDEX",
  "EDMG_CUDA_WHEEL_TAG",
  "PIP_TORCH_INDEX_URL",
  "PIP_CONFIG_FILE",
  "PIP_FIND_LINKS",
  "PIP_INDEX_URL",
  "PIP_EXTRA_INDEX_URL",
  "UV_CONFIG_FILE",
  "UV_DEFAULT_INDEX",
  "UV_EXTRA_INDEX_URL",
  "UV_FIND_LINKS",
  "UV_INDEX",
  "UV_INDEX_URL",
  "UV_NO_SOURCES",
  "UV_PROJECT_ENVIRONMENT",
]);

function nonEmptyEnvValue(env, key) {
  return String(env?.[key] ?? "").trim();
}

export function assertNoDynamicDependencyOverrides(env = process.env) {
  const configured = DYNAMIC_DEPENDENCY_ENV_VARS.filter((key) => nonEmptyEnvValue(env, key));
  if (configured.length) {
    throw new Error(
      `Release dependency/index overrides are forbidden: ${configured.join(", ")}. ` +
        "Update pyproject.toml and uv.lock instead.",
    );
  }
}

function parseProfileArgs(argv) {
  const values = [];
  for (let index = 0; index < argv.length; index += 1) {
    const arg = String(argv[index] ?? "");
    if (arg === "--profile") {
      if (index + 1 >= argv.length) throw new Error("--profile requires a value");
      values.push(String(argv[index + 1]));
      index += 1;
      continue;
    }
    if (arg.startsWith("--profile=")) {
      values.push(arg.slice("--profile=".length));
      continue;
    }
    throw new Error(`Unknown prepare-release-bundle argument: ${arg}`);
  }
  if (values.length > 1) throw new Error("Specify exactly one accelerator profile");
  return values[0] ?? "";
}

export function resolveAcceleratorProfile({ argv = [], env = process.env, platform = process.platform } = {}) {
  const fromArgs = parseProfileArgs(argv).trim();
  const fromEnv = String(env.EDMG_BACKEND_ACCELERATOR_PROFILE ?? "").trim();
  if (fromArgs && fromEnv && fromArgs !== fromEnv) {
    throw new Error(`Conflicting accelerator profiles: --profile=${fromArgs} and EDMG_BACKEND_ACCELERATOR_PROFILE=${fromEnv}`);
  }

  const profile = fromArgs || fromEnv || (platform === "win32" ? "directml" : "cpu");
  if (!ACCELERATOR_PROFILES.includes(profile)) {
    throw new Error(
      `Invalid accelerator profile ${JSON.stringify(profile)}. Expected exactly one of: ${ACCELERATOR_PROFILES.join(", ")}`,
    );
  }
  if (profile === "directml" && platform !== "win32") {
    throw new Error("The directml release profile is supported only on Windows");
  }
  return profile;
}

export function selectedExtras(profile) {
  if (!ACCELERATOR_PROFILES.includes(profile)) throw new Error(`Unsupported accelerator profile: ${profile}`);
  return [profile, ...RELEASE_CAPABILITY_EXTRAS];
}

export function releaseUvEnvironment(studioRoot, profile, env = process.env) {
  if (!ACCELERATOR_PROFILES.includes(profile)) throw new Error(`Unsupported accelerator profile: ${profile}`);
  return {
    ...env,
    // Release builds must not share the source-runtime .venv. A running Studio
    // instance may legitimately sync a different accelerator profile there.
    UV_PROJECT_ENVIRONMENT: path.join(studioRoot, "release", "uv-environments", profile),
    // The global uv cache and this repository can live on different Windows
    // volumes. Copy mode avoids a noisy hardlink attempt and fallback.
    UV_LINK_MODE: "copy",
  };
}

function extraArgs(profile) {
  return selectedExtras(profile).flatMap((extra) => ["--extra", extra]);
}

export function uvLockCheckArgs() {
  return ["lock", "--check"];
}

export function uvSyncArgs(profile) {
  return ["sync", "--frozen", "--no-default-groups", ...extraArgs(profile), "--group", "build"];
}

export function uvRunArgs(profile, commandArgs) {
  return [
    "run",
    "--frozen",
    "--no-sync",
    "--no-default-groups",
    ...extraArgs(profile),
    "--group",
    "build",
    ...commandArgs,
  ];
}

export function uvExportCycloneDxArgs(profile) {
  return ["export", "--format", "cyclonedx1.5", "--frozen", "--no-default-groups", ...extraArgs(profile), "--group", "build"];
}

export function parseUvVersion(output) {
  const match = String(output ?? "").trim().match(/^uv\s+(\d+\.\d+\.\d+)(?:\s|$)/);
  if (!match) throw new Error(`Could not parse uv version output: ${JSON.stringify(String(output ?? "").trim())}`);
  return match[1];
}

export function assertPinnedUvVersion(output, expected = PINNED_UV_VERSION) {
  const actual = parseUvVersion(output);
  if (actual !== expected) {
    throw new Error(`uv ${actual} is unsupported for release builds; install the pinned uv ${expected}`);
  }
  return actual;
}

export function assertPython312(version) {
  const value = String(version ?? "").trim();
  if (!/^3\.12(?:\.|$)/.test(value)) {
    throw new Error(`Release Python ${value || "unknown"} is unsupported; Python 3.12 is required`);
  }
  return value;
}

export function assertTrackedCleanDependencyStatus({ trackedStatus, dirtyStatus, paths }) {
  if (trackedStatus !== 0) {
    throw new Error(`Release dependency inputs must be tracked by git: ${paths.join(", ")}`);
  }
  if (String(dirtyStatus ?? "").trim()) {
    throw new Error(
      "Release dependency inputs must be committed and clean before packaging:\n" + String(dirtyStatus).trim(),
    );
  }
}

export function normalizeTorchIndex(value) {
  return String(value ?? "").trim().replace(/\/+$/, "");
}

export function assertTorchIndexForProfile(profile, index) {
  const normalized = normalizeTorchIndex(index);
  if (profile === "cpu" || profile === "directml") {
    if (normalized !== "https://download.pytorch.org/whl/cpu") {
      throw new Error(`${profile} releases must use the locked PyTorch CPU index; got ${normalized || "none"}`);
    }
    return normalized;
  }
  if (profile === "cuda") {
    if (!/^https:\/\/download\.pytorch\.org\/whl\/cu\d+$/.test(normalized)) {
      throw new Error(`CUDA releases must use a fixed locked PyTorch CUDA index; got ${normalized || "none"}`);
    }
    return normalized;
  }
  throw new Error(`Unsupported accelerator profile: ${profile}`);
}

function isSha256(value) {
  return /^[a-f0-9]{64}$/.test(String(value ?? ""));
}

function sameStringArray(left, right) {
  return Array.isArray(left) && Array.isArray(right) &&
    left.length === right.length && left.every((value, index) => value === right[index]);
}

function normalizedTorchPackages(packages) {
  if (!Array.isArray(packages)) return [];
  return packages
    .map((entry) => ({
      name: String(entry?.name ?? ""),
      version: String(entry?.version ?? ""),
      index: normalizeTorchIndex(entry?.index),
    }))
    .sort((left, right) => left.name.localeCompare(right.name));
}

export function validateReleaseManifest(manifest, { expectedProfile = "", expectedUvVersion = PINNED_UV_VERSION } = {}) {
  const errors = [];
  if (!manifest || typeof manifest !== "object") return ["manifest is not an object"];
  if (manifest.schemaVersion !== RELEASE_MANIFEST_SCHEMA_VERSION) errors.push("schemaVersion must be 2");
  if (manifest.ok !== true) errors.push("ok must be true");
  if (!isSha256(manifest.sourceHash)) errors.push("sourceHash must be a SHA-256 digest");
  if (!isSha256(manifest.lockSha256)) errors.push("lockSha256 must be a SHA-256 digest");
  if (!isSha256(manifest.binarySha256)) errors.push("binarySha256 must be a SHA-256 digest");
  if (!ACCELERATOR_PROFILES.includes(manifest.acceleratorProfile)) errors.push("acceleratorProfile is invalid");
  if (expectedProfile && manifest.acceleratorProfile !== expectedProfile) {
    errors.push(`acceleratorProfile must be ${expectedProfile}`);
  }
  if (!sameStringArray(manifest.capabilityExtras, RELEASE_CAPABILITY_EXTRAS)) {
    errors.push("capabilityExtras do not match the release capability set");
  }
  if (manifest.uvVersion !== expectedUvVersion) errors.push(`uvVersion must be ${expectedUvVersion}`);
  if (!/^3\.12(?:\.|$)/.test(String(manifest.pythonVersion ?? ""))) errors.push("pythonVersion must be Python 3.12");
  if (!String(manifest.pyinstallerVersion ?? "").trim()) errors.push("pyinstallerVersion is required");
  if (!Number.isInteger(manifest.sourceFileCount) || manifest.sourceFileCount <= 0) errors.push("sourceFileCount is invalid");
  if (!Number.isInteger(manifest.binarySize) || manifest.binarySize <= 0) errors.push("binarySize is invalid");

  const torchPackages = normalizedTorchPackages(manifest.torchPackages);
  const expectedNames = ["torch", "torchaudio", "torchvision"];
  if (!sameStringArray(torchPackages.map((entry) => entry.name), expectedNames)) {
    errors.push("torchPackages must contain torch, torchaudio, and torchvision");
  }
  for (const entry of torchPackages) {
    if (!entry.version) errors.push(`torchPackages.${entry.name}.version is required`);
    if (entry.index !== normalizeTorchIndex(manifest.torchIndex)) {
      errors.push(`torchPackages.${entry.name}.index does not match torchIndex`);
    }
  }
  if (ACCELERATOR_PROFILES.includes(manifest.acceleratorProfile)) {
    try {
      assertTorchIndexForProfile(manifest.acceleratorProfile, manifest.torchIndex);
    } catch (error) {
      errors.push(error.message);
    }
  }

  if (!Array.isArray(manifest.fingerprintInputs) || manifest.fingerprintInputs.length < 3) {
    errors.push("fingerprintInputs must include the Python and lock metadata");
  } else {
    const requiredSuffixes = [".python-version", "python_backend/pyproject.toml", "python_backend/uv.lock"];
    for (const suffix of requiredSuffixes) {
      const entry = manifest.fingerprintInputs.find((candidate) => String(candidate?.path ?? "").replaceAll("\\", "/").endsWith(suffix));
      if (!entry || !isSha256(entry.sha256)) errors.push(`fingerprintInputs is missing ${suffix}`);
    }
  }
  if (!Array.isArray(manifest.nltkResources) || !manifest.nltkResources.length) {
    errors.push("nltkResources provenance is required");
  } else {
    for (const entry of manifest.nltkResources) {
      if (!String(entry?.name ?? "") || !String(entry?.url ?? "") || !isSha256(entry?.sha256)) {
        errors.push("nltkResources entries require name, immutable URL, and SHA-256");
        break;
      }
    }
  }
  return errors;
}

export function assertValidReleaseManifest(manifest, options = {}) {
  const errors = validateReleaseManifest(manifest, options);
  if (errors.length) throw new Error(`Invalid backend release manifest: ${errors.join("; ")}`);
  return manifest;
}

export function releaseProvenanceMatches(manifest, expected) {
  if (validateReleaseManifest(manifest, { expectedProfile: expected.acceleratorProfile }).length) return false;
  return manifest.sourceHash === expected.sourceHash &&
    manifest.lockSha256 === expected.lockSha256 &&
    manifest.uvVersion === expected.uvVersion &&
    manifest.pythonVersion === expected.pythonVersion &&
    manifest.pythonImplementation === expected.pythonImplementation &&
    manifest.pyinstallerVersion === expected.pyinstallerVersion &&
    manifest.torchIndex === expected.torchIndex &&
    JSON.stringify(normalizedTorchPackages(manifest.torchPackages)) === JSON.stringify(normalizedTorchPackages(expected.torchPackages)) &&
    JSON.stringify(manifest.nltkResources) === JSON.stringify(expected.nltkResources) &&
    JSON.stringify(manifest.fingerprintInputs) === JSON.stringify(expected.fingerprintInputs) &&
    sameStringArray(manifest.capabilityExtras, expected.capabilityExtras);
}

export async function sha256File(filePath) {
  const hash = crypto.createHash("sha256");
  await new Promise((resolve, reject) => {
    const stream = fs.createReadStream(filePath);
    stream.on("data", (chunk) => hash.update(chunk));
    stream.on("error", reject);
    stream.on("end", resolve);
  });
  return hash.digest("hex");
}

export async function fileFingerprintEntries(files, baseDir) {
  const entries = [];
  for (const filePath of files) {
    entries.push({
      path: filePath.replace(baseDir, "").replace(/^[/\\]+/, "").split("\\").join("/"),
      sha256: await sha256File(filePath),
    });
  }
  return entries;
}

export async function binaryMatchesManifest(binaryPath, manifest) {
  if (!fs.existsSync(binaryPath) || !isSha256(manifest?.binarySha256)) return false;
  const stat = await fsp.stat(binaryPath);
  if (manifest.binarySize !== stat.size) return false;
  return (await sha256File(binaryPath)) === manifest.binarySha256;
}
