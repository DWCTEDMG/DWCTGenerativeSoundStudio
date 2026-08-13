import crypto from "node:crypto";
import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import { spawnSync } from "node:child_process";

import {
  PINNED_UV_VERSION,
  resolveAcceleratorProfile,
  selectedExtras,
  sha256File,
  uvExportCycloneDxArgs,
} from "./release-python-toolchain.mjs";

export const RELEASE_EVIDENCE_SCHEMA_VERSION = 1;
export const RELEASE_EVIDENCE_DIR = "release/evidence";

const RELEASE_ARTIFACT_GLOBS = Object.freeze({
  bundle: [
    "electron-resources/backend/backend-bundle-manifest.json",
    "electron-resources/backend/edmg-studio-backend.exe",
    "electron-resources/backend/edmg-studio-backend",
    "electron-resources/director/director-bundle-manifest.json",
    "python_backend/uv.lock",
  ],
});

export const RELEASE_ARTIFACT_SETS = Object.freeze([
  "win-nsis",
  "linux-appimage",
  "win-inno",
  "win-inno-cuda",
]);

const DIST_ARTIFACT_GLOBS = Object.freeze({
  "win-nsis": [
    "dist/*.exe",
    "dist/*.blockmap",
    "dist/latest*.yml",
    "dist/builder-effective-config.yaml",
  ],
  "linux-appimage": [
    "dist/*.AppImage",
    "dist/latest-linux.yml",
    "dist/builder-effective-config.yaml",
  ],
  "win-inno": [
    "dist-inno/*.exe",
    "dist-inno/payload/*.7z",
    "dist-inno/payload/payload-integrity.json",
    "dist/builder-effective-config.yaml",
  ],
  "win-inno-cuda": [
    "dist-inno-cuda/*.exe",
    "dist-inno-cuda/payload/*.7z",
    "dist-inno-cuda/payload/payload-integrity.json",
    "dist/builder-effective-config.yaml",
  ],
});

function repoRelative(root, filePath) {
  return path.relative(root, filePath).split(path.sep).join("/");
}

function expandGlob(root, pattern) {
  const normalized = pattern.split("/").join(path.sep);
  const starIndex = normalized.indexOf("*");
  if (starIndex === -1) {
    const absolute = path.join(root, normalized);
    return fs.existsSync(absolute) ? [absolute] : [];
  }

  const base = normalized.slice(0, starIndex).replace(/[/\\]+$/, "");
  const suffix = normalized.slice(starIndex + 1);
  const baseDir = path.join(root, base);
  if (!fs.existsSync(baseDir) || !fs.statSync(baseDir).isDirectory()) return [];

  return fs
    .readdirSync(baseDir)
    .filter((name) => name.endsWith(suffix))
    .map((name) => path.join(baseDir, name))
    .filter((candidate) => fs.statSync(candidate).isFile());
}

export function collectReleaseArtifactPaths(root, phase = "bundle", artifactSet = "") {
  if (!["bundle", "dist"].includes(phase)) {
    throw new Error(`Unsupported release evidence phase: ${JSON.stringify(phase)}`);
  }
  const normalizedArtifactSet = String(artifactSet || "").trim();
  const wantsDist = phase === "dist";
  if (wantsDist && !RELEASE_ARTIFACT_SETS.includes(normalizedArtifactSet)) {
    throw new Error(
      `A dist artifact set is required (${RELEASE_ARTIFACT_SETS.join(", ")}); received ${JSON.stringify(normalizedArtifactSet)}`,
    );
  }
  const patterns = [
    ...(phase === "bundle" ? RELEASE_ARTIFACT_GLOBS.bundle : []),
    ...(wantsDist ? DIST_ARTIFACT_GLOBS[normalizedArtifactSet] : []),
  ];
  const seen = new Set();
  const files = [];

  for (const pattern of patterns) {
    for (const filePath of expandGlob(root, pattern)) {
      const key = filePath.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      files.push(filePath);
    }
  }

  return files.sort((left, right) => repoRelative(root, left).localeCompare(repoRelative(root, right)));
}

export function resolveCodeSigningConfig(env = process.env) {
  const certificate = String(env.EDMG_CODE_SIGN_CERT ?? "").trim();
  const password = String(env.EDMG_CODE_SIGN_PASSWORD ?? "").trim();
  const timestampUrl = String(env.EDMG_CODE_SIGN_TIMESTAMP_URL ?? "http://timestamp.digicert.com").trim();
  const enabled = Boolean(certificate);

  return {
    enabled,
    certificate,
    passwordConfigured: Boolean(password),
    timestampUrl,
    tool: process.platform === "win32" ? "signtool.exe" : process.platform === "darwin" ? "codesign" : "osslsigncode",
    reason: enabled
      ? "EDMG_CODE_SIGN_CERT is configured for the Windows packaging signing lane."
      : "Set EDMG_CODE_SIGN_CERT to a Windows certificate thumbprint or PFX path to enable signing.",
  };
}

export function planCodeSigning(config, artifactPaths, root = process.cwd()) {
  const signable = artifactPaths.filter((filePath) => /\.(exe|msi|appimage)$/i.test(filePath));
  if (!config.enabled) {
    return {
      attempted: false,
      signed: [],
      skipped: signable.map((filePath) => repoRelative(root, filePath)),
      reason: config.reason,
    };
  }
  if (!signable.length) {
    return {
      attempted: false,
      signed: [],
      skipped: [],
      reason: "No installer artifacts were present for signing.",
    };
  }
  return {
    attempted: false,
    signed: [],
    skipped: signable.map((filePath) => repoRelative(root, filePath)),
    reason: "Signing is performed and verified by packaging/windows/sign_release.ps1; inspect windows-signatures.json.",
  };
}

export function readWindowsSignatureEvidence(root, artifactPaths = null) {
  const evidencePath = path.join(root, RELEASE_EVIDENCE_DIR, "windows-signatures.json");
  const allowedPaths = Array.isArray(artifactPaths)
    ? new Set(
        artifactPaths
          .filter((filePath) => /\.(exe|msi)$/i.test(filePath))
          .map((filePath) => repoRelative(root, filePath).toLowerCase()),
      )
    : null;
  if (!fs.existsSync(evidencePath)) {
    return {
      exists: false,
      evidencePath,
      attempted: false,
      valid: [],
      skipped: [],
      failed: [],
    };
  }

  let document;
  try {
    document = JSON.parse(fs.readFileSync(evidencePath, "utf8"));
  } catch (error) {
    throw new Error(`Windows signature evidence is invalid JSON: ${error.message}`);
  }
  if (document?.schemaVersion !== 1 || !Array.isArray(document?.runs)) {
    throw new Error("Windows signature evidence must use schemaVersion 1 with a runs array.");
  }

  const latestByPath = new Map();
  for (const run of document.runs) {
    for (const artifact of Array.isArray(run?.artifacts) ? run.artifacts : []) {
      const artifactPath = String(artifact?.path || "").trim().replaceAll("\\", "/");
      const normalizedPath = artifactPath.toLowerCase();
      if (!artifactPath || (allowedPaths && !allowedPaths.has(normalizedPath))) continue;
      latestByPath.set(normalizedPath, { artifactPath, artifact });
    }
  }

  const valid = [];
  const skipped = [];
  const failed = [];
  for (const { artifactPath, artifact } of latestByPath.values()) {
    if (artifact.authenticodeStatus === "Valid" && artifact.signToolVerified === true) {
      valid.push(artifactPath);
    } else if (artifact.action === "skipped") {
      skipped.push(artifactPath);
    } else {
      failed.push(artifactPath);
    }
  }
  return {
    exists: true,
    evidencePath,
    attempted: document.runs.length > 0,
    valid: valid.sort(),
    skipped: skipped.sort(),
    failed: failed.sort(),
  };
}

export function generatePythonSbom({
  root,
  uvCommand,
  profile,
  outputPath,
  env = process.env,
}) {
  const resolvedProfile = resolveAcceleratorProfile({ argv: [`--profile=${profile}`], env, platform: process.platform });
  const pythonBackendDir = path.join(root, "python_backend");
  const args = [...uvExportCycloneDxArgs(resolvedProfile), "-o", outputPath];
  const result = spawnSync(uvCommand, args, {
    cwd: pythonBackendDir,
    env,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    shell: false,
  });
  if (result.error) throw new Error(`SBOM export failed: ${result.error.message}`);
  if (result.status !== 0) {
    const detail = String(result.stderr || result.stdout || "").trim();
    throw new Error(`SBOM export failed with exit code ${result.status ?? "unknown"}${detail ? `: ${detail}` : ""}`);
  }
  if (!fs.existsSync(outputPath)) {
    throw new Error(`SBOM export completed but output is missing: ${outputPath}`);
  }

  let document = null;
  try {
    document = JSON.parse(fs.readFileSync(outputPath, "utf8"));
  } catch {
    throw new Error(`SBOM export wrote invalid JSON: ${outputPath}`);
  }

  return {
    format: "CycloneDX",
    version: String(document?.specVersion || "1.5"),
    profile: resolvedProfile,
    extras: selectedExtras(resolvedProfile),
    outputPath,
    componentCount: Array.isArray(document?.components) ? document.components.length : 0,
    uvVersion: PINNED_UV_VERSION,
    reusedExisting: false,
  };
}

export function readPythonSbom({ profile, outputPath, version = "", env = process.env }) {
  const resolvedProfile = resolveAcceleratorProfile({
    argv: [`--profile=${profile}`],
    env,
    platform: process.platform,
  });
  if (!fs.existsSync(outputPath)) {
    throw new Error(`Existing SBOM is required but missing: ${outputPath}`);
  }

  let document = null;
  try {
    document = JSON.parse(fs.readFileSync(outputPath, "utf8"));
  } catch {
    throw new Error(`Existing SBOM is invalid JSON: ${outputPath}`);
  }
  const tool = Array.isArray(document?.metadata?.tools)
    ? document.metadata.tools.find((candidate) => candidate?.name === "uv")
    : document?.metadata?.tools;
  if (
    document?.bomFormat !== "CycloneDX"
    || document?.specVersion !== "1.5"
    || tool?.name !== "uv"
    || tool?.version !== PINNED_UV_VERSION
    || document?.metadata?.component?.name !== "edmg-studio-backend"
    || (version && document?.metadata?.component?.version !== version)
    || !Array.isArray(document?.components)
    || !Array.isArray(document?.dependencies)
  ) {
    throw new Error(`Existing SBOM is not a valid CycloneDX document: ${outputPath}`);
  }

  return {
    format: "CycloneDX",
    version: String(document.specVersion),
    profile: resolvedProfile,
    extras: selectedExtras(resolvedProfile),
    outputPath,
    componentCount: Array.isArray(document.components) ? document.components.length : 0,
    uvVersion: PINNED_UV_VERSION,
    reusedExisting: true,
  };
}

export async function validateBundleEvidenceForSbomReuse({ root, profile, version = "", sbomPath }) {
  const bundleEvidencePath = path.join(root, RELEASE_EVIDENCE_DIR, "bundle-artifacts.sha256.json");
  if (!fs.existsSync(bundleEvidencePath)) {
    throw new Error(`Bundle checksum evidence is required before dist evidence: ${bundleEvidencePath}`);
  }

  let document = null;
  try {
    document = JSON.parse(fs.readFileSync(bundleEvidencePath, "utf8"));
  } catch {
    throw new Error(`Bundle checksum evidence is invalid JSON: ${bundleEvidencePath}`);
  }
  const resolvedProfile = resolveAcceleratorProfile({
    argv: [`--profile=${profile}`],
    env: process.env,
    platform: process.platform,
  });
  if (
    document?.schemaVersion !== RELEASE_EVIDENCE_SCHEMA_VERSION
    || document?.phase !== "bundle"
    || document?.acceleratorProfile !== resolvedProfile
    || (version && document?.studioVersion !== version)
    || !Array.isArray(document?.artifacts)
  ) {
    throw new Error("Bundle checksum evidence does not match the requested dist profile and version.");
  }

  const expectedManifestHash = crypto
    .createHash("sha256")
    .update(JSON.stringify({ ...document, manifestSha256: undefined }))
    .digest("hex");
  if (document.manifestSha256 !== expectedManifestHash) {
    throw new Error("Bundle checksum evidence self-hash is invalid.");
  }

  const rootPrefix = `${path.resolve(root)}${path.sep}`.toLowerCase();
  for (const artifact of document.artifacts) {
    const artifactPath = path.resolve(root, String(artifact?.path || "").split("/").join(path.sep));
    if (!artifactPath.toLowerCase().startsWith(rootPrefix)) {
      throw new Error(`Bundle checksum evidence contains an unsafe artifact path: ${artifact?.path}`);
    }
    let stat = null;
    try {
      stat = await fsp.stat(artifactPath);
    } catch {
      throw new Error(`Bundle checksum artifact is missing: ${artifact?.path}`);
    }
    if (!stat.isFile() || stat.size !== artifact?.bytes || (await sha256File(artifactPath)) !== artifact?.sha256) {
      throw new Error(`Bundle checksum artifact does not match current bytes: ${artifact?.path}`);
    }
  }

  const expectedSbomPath = repoRelative(root, sbomPath);
  if (!document.artifacts.some((artifact) => artifact.path === expectedSbomPath)) {
    throw new Error(`Bundle checksum evidence does not bind the expected SBOM: ${expectedSbomPath}`);
  }
  if (!document.artifacts.some((artifact) => artifact.path === "python_backend/uv.lock")) {
    throw new Error("Bundle checksum evidence does not bind python_backend/uv.lock.");
  }
  return document;
}

export async function buildChecksumManifest({
  root,
  artifactPaths,
  metadata = {},
}) {
  const artifacts = [];
  for (const filePath of artifactPaths) {
    const stat = await fsp.stat(filePath);
    artifacts.push({
      path: repoRelative(root, filePath),
      sha256: await sha256File(filePath),
      bytes: stat.size,
    });
  }

  const manifest = {
    schemaVersion: RELEASE_EVIDENCE_SCHEMA_VERSION,
    generatedAt: new Date().toISOString(),
    artifacts,
    ...metadata,
  };
  manifest.manifestSha256 = crypto
    .createHash("sha256")
    .update(JSON.stringify({ ...manifest, manifestSha256: undefined }))
    .digest("hex");
  return manifest;
}

export async function writeReleaseEvidence({
  root,
  phase = "bundle",
  profile,
  artifactSet = "",
  uvCommand = "uv",
  version = "",
  env = process.env,
  reuseExistingSbom,
}) {
  if (!["bundle", "dist"].includes(phase)) {
    throw new Error(`Unsupported release evidence phase: ${JSON.stringify(phase)}`);
  }
  const evidenceDir = path.join(root, RELEASE_EVIDENCE_DIR);
  await fsp.mkdir(evidenceDir, { recursive: true });

  const resolvedProfile = resolveAcceleratorProfile({ argv: [`--profile=${profile}`], env, platform: process.platform });
  const sbomPath = path.join(evidenceDir, `python-backend-${resolvedProfile}.cyclonedx.json`);
  if (reuseExistingSbom === true && phase !== "bundle") {
    throw new Error("Explicit existing-SBOM reuse is only supported for bundle evidence repair.");
  }
  const shouldReuseSbom = phase === "dist" || reuseExistingSbom === true;
  if (shouldReuseSbom && phase === "dist") {
    await validateBundleEvidenceForSbomReuse({
      root,
      profile: resolvedProfile,
      version,
      sbomPath,
    });
  }
  const sbom = shouldReuseSbom
    ? readPythonSbom({ profile: resolvedProfile, outputPath: sbomPath, version, env })
    : generatePythonSbom({ root, uvCommand, profile: resolvedProfile, outputPath: sbomPath, env });

  const artifactPaths = collectReleaseArtifactPaths(root, phase, artifactSet);
  if (fs.existsSync(sbomPath) && !artifactPaths.includes(sbomPath)) {
    artifactPaths.push(sbomPath);
    artifactPaths.sort((left, right) => repoRelative(root, left).localeCompare(repoRelative(root, right)));
  }

  const signing = resolveCodeSigningConfig(env);
  const signingPlan = planCodeSigning(signing, artifactPaths, root);
  const windowsSignatures = readWindowsSignatureEvidence(root, artifactPaths);
  const signingReason = windowsSignatures.exists
    ? `Authenticode evidence: ${windowsSignatures.valid.length} verified, ${windowsSignatures.skipped.length} skipped, ${windowsSignatures.failed.length} failed.`
    : signingPlan.reason;
  const checksumManifest = await buildChecksumManifest({
    root,
    artifactPaths,
    metadata: {
      phase,
      artifactSet: artifactSet || undefined,
      studioVersion: version || undefined,
      acceleratorProfile: resolvedProfile,
      sbom: {
        format: sbom.format,
        version: sbom.version,
        path: repoRelative(root, sbomPath),
        componentCount: sbom.componentCount,
      },
      codeSigning: {
        enabled: signing.enabled || windowsSignatures.valid.length > 0,
        attempted: signingPlan.attempted || windowsSignatures.attempted,
        tool: signing.tool,
        reason: signingReason,
        evidencePath: windowsSignatures.exists ? repoRelative(root, windowsSignatures.evidencePath) : undefined,
        signedCount: windowsSignatures.valid.length,
        skippedCount: windowsSignatures.exists ? windowsSignatures.skipped.length : signingPlan.skipped.length,
        failedCount: windowsSignatures.failed.length,
      },
    },
  });

  const checksumPath = path.join(evidenceDir, phase === "dist" ? "release-artifacts.sha256.json" : "bundle-artifacts.sha256.json");
  await fsp.writeFile(checksumPath, JSON.stringify(checksumManifest, null, 2) + "\n", "utf8");

  const indexPath = path.join(evidenceDir, "release-evidence.json");
  const index = {
    schemaVersion: RELEASE_EVIDENCE_SCHEMA_VERSION,
    updatedAt: new Date().toISOString(),
    phase,
    artifactSet: artifactSet || undefined,
    studioVersion: version || undefined,
    acceleratorProfile: resolvedProfile,
    sbomPath: repoRelative(root, sbomPath),
    checksumManifestPath: repoRelative(root, checksumPath),
    artifactCount: checksumManifest.artifacts.length,
    codeSigning: checksumManifest.codeSigning,
  };
  await fsp.writeFile(indexPath, JSON.stringify(index, null, 2) + "\n", "utf8");

  return {
    ok: true,
    evidenceDir,
    indexPath,
    checksumPath,
    sbomPath,
    sbom,
    checksumManifest,
    signingPlan,
  };
}
