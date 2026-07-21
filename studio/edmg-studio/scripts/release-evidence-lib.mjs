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
  dist: [
    "dist/*.exe",
    "dist/*.blockmap",
    "dist/*.AppImage",
    "dist/latest*.yml",
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

export function collectReleaseArtifactPaths(root, phase = "bundle") {
  const phases = phase === "all" ? ["bundle", "dist"] : [phase];
  const patterns = phases.flatMap((entry) => RELEASE_ARTIFACT_GLOBS[entry] || []);
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
      ? "EDMG_CODE_SIGN_CERT is configured; signing runs when dist artifacts exist."
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
    attempted: true,
    signed: [],
    skipped: signable.map((filePath) => repoRelative(root, filePath)),
    reason: "Signing hook is configured but intentionally stubbed in this repository slice.",
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
  };
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
  uvCommand = "uv",
  version = "",
  env = process.env,
}) {
  const evidenceDir = path.join(root, RELEASE_EVIDENCE_DIR);
  await fsp.mkdir(evidenceDir, { recursive: true });

  const resolvedProfile = resolveAcceleratorProfile({ argv: [`--profile=${profile}`], env, platform: process.platform });
  const sbomPath = path.join(evidenceDir, `python-backend-${resolvedProfile}.cyclonedx.json`);
  const sbom = generatePythonSbom({ root, uvCommand, profile: resolvedProfile, outputPath: sbomPath, env });

  const artifactPaths = collectReleaseArtifactPaths(root, phase);
  if (fs.existsSync(sbomPath) && !artifactPaths.includes(sbomPath)) {
    artifactPaths.push(sbomPath);
    artifactPaths.sort((left, right) => repoRelative(root, left).localeCompare(repoRelative(root, right)));
  }

  const signing = resolveCodeSigningConfig(env);
  const signingPlan = planCodeSigning(signing, artifactPaths, root);
  const checksumManifest = await buildChecksumManifest({
    root,
    artifactPaths,
    metadata: {
      phase,
      studioVersion: version || undefined,
      acceleratorProfile: resolvedProfile,
      sbom: {
        format: sbom.format,
        version: sbom.version,
        path: repoRelative(root, sbomPath),
        componentCount: sbom.componentCount,
      },
      codeSigning: {
        enabled: signing.enabled,
        attempted: signingPlan.attempted,
        tool: signing.tool,
        reason: signingPlan.reason,
        signedCount: signingPlan.signed.length,
        skippedCount: signingPlan.skipped.length,
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
