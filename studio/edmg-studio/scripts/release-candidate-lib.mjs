import crypto from "node:crypto";
import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import { execFile, execFileSync } from "node:child_process";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

export const CANDIDATE_SCHEMA_VERSION = 1;
const execFileAsync = promisify(execFile);
const HEX64 = /^[a-f0-9]{64}$/;

export function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export function sha256Bytes(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

export async function sha256File(filePath) {
  const hash = crypto.createHash("sha256");
  const stream = fs.createReadStream(filePath);
  for await (const chunk of stream) hash.update(chunk);
  return hash.digest("hex");
}

function git(repoRoot, args, encoding = "utf8") {
  return execFileSync("git", ["-C", repoRoot, ...args], { encoding, windowsHide: true });
}

export async function collectGitProvenance(repoRoot) {
  const commitSha = git(repoRoot, ["rev-parse", "HEAD"]).trim();
  const trackedPatch = git(repoRoot, ["diff", "--binary", "--no-ext-diff", "HEAD"], "buffer");
  const untracked = git(repoRoot, ["ls-files", "--others", "--exclude-standard", "-z"], "buffer")
    .toString("utf8").split("\0").filter(Boolean).sort();
  const hash = crypto.createHash("sha256");
  hash.update(Buffer.from("tracked\0"));
  hash.update(trackedPatch);
  for (const relative of untracked) {
    hash.update(Buffer.from(`\0untracked\0${relative.replaceAll("\\", "/")}\0`));
    hash.update(await fsp.readFile(path.join(repoRoot, relative)));
  }
  const dirty = trackedPatch.length > 0 || untracked.length > 0;
  return {
    commitSha,
    dirty,
    dirtyPatchSha256: dirty ? hash.digest("hex") : null,
    untrackedFileCount: untracked.length,
  };
}

async function hashExisting(repoRoot, relativePaths) {
  const rows = [];
  for (const relativePath of relativePaths) {
    const absolute = path.join(repoRoot, relativePath);
    if (!fs.existsSync(absolute)) throw new Error(`Candidate input is missing: ${relativePath}`);
    rows.push({ path: relativePath.replaceAll("\\", "/"), sha256: await sha256File(absolute) });
  }
  return rows;
}

function toolVersion(command, args) {
  try { return execFileSync(command, args, { encoding: "utf8", windowsHide: true }).trim().split(/\r?\n/, 1)[0]; }
  catch { return "unavailable"; }
}

export function backendPayloadIdentity(manifest) {
  const entries = [...(manifest.bundleEntries || [])]
    .filter((entry) => entry.type === "file")
    .map(({ path: entryPath, size, sha256 }) => ({ path: entryPath, size, sha256 }))
    .sort((a, b) => a.path.localeCompare(b.path));
  if (!manifest.sourceHash || !manifest.binarySha256 || entries.length === 0) {
    throw new Error("Backend manifest lacks source, binary, or payload inventory hashes.");
  }
  return {
    sourceSha256: manifest.sourceHash,
    sourceFileCount: manifest.sourceFileCount,
    payloadTreeSha256: sha256Bytes(stableJson(entries)),
    payloadFileCount: entries.length,
    binarySha256: manifest.binarySha256,
    acceleratorProfile: manifest.acceleratorProfile,
    lockSha256: manifest.lockSha256,
  };
}

export async function createCandidate({ repoRoot, studioRoot, backendManifestPath = "", vst3HostPath = "", vst3ScannerPath = "", mode = "developer", storeMetadata = null, packageIdentity = null, sourceDateEpoch = "" }) {
  if (!["developer", "production", "store"].includes(mode)) throw new Error(`Unsupported candidate mode: ${mode}`);
  const gitState = await collectGitProvenance(repoRoot);
  if (mode !== "developer" && gitState.dirty) throw new Error("Production/Store candidates require a clean Git tree.");
  const inputPaths = [
    ".python-version", "studio/edmg-studio-winui/global.json", "studio/edmg-studio/package.json", "studio/edmg-studio/pnpm-lock.yaml",
    "studio/edmg-studio/python_backend/pyproject.toml", "studio/edmg-studio/python_backend/uv.lock",
    "studio/edmg-studio/python_backend/hf_bucket_helper/uv.lock",
    "studio/edmg-studio-winui/EdmgStudio.WinUI.csproj", "studio/edmg-studio-winui/Package.appxmanifest",
    "studio/edmg-studio-winui/native/vst3-host/CMakeLists.txt",
    "studio/edmg-studio-winui/native/vst3-host/src/main.cpp",
    "studio/edmg-studio-winui/native/vst3-host/THIRD-PARTY-NOTICES.txt",
    "studio/edmg-studio/packaging/media-tools-assets.json",
  ];
  const inputs = await hashExisting(repoRoot, inputPaths);
  let backend = null;
  if (backendManifestPath) backend = backendPayloadIdentity(JSON.parse(await fsp.readFile(backendManifestPath, "utf8")));
  if (mode !== "developer" && !backend) throw new Error("Production/Store candidates require the validated production backend payload.");
  let nativeVst3Host = null;
  if (vst3HostPath) {
    const resolvedHostPath = path.resolve(vst3HostPath);
    const stat = await fsp.stat(resolvedHostPath);
    if (!stat.isFile()) throw new Error("VST3 host candidate input must be a regular file.");
    nativeVst3Host = {
      fileName: path.basename(resolvedHostPath),
      bytes: stat.size,
      sha256: await sha256File(resolvedHostPath),
      architecture: "x64",
      configuration: "Release",
      sdkVersion: "3.8.1",
      sdkCommit: "3cdf9ca5d1f5b1b21e0a86832aa4abe55607bd96",
    };
  }
  if (!nativeVst3Host) throw new Error("Candidates require the exact EdmgStudio.Vst3Host.exe payload.");
  let nativeVst3Scanner = null;
  if (vst3ScannerPath) {
    const resolvedScannerPath = path.resolve(vst3ScannerPath);
    const stat = await fsp.stat(resolvedScannerPath);
    if (!stat.isFile()) throw new Error("VST3 scanner candidate input must be a regular file.");
    nativeVst3Scanner = {
      fileName: path.basename(resolvedScannerPath),
      bytes: stat.size,
      sha256: await sha256File(resolvedScannerPath),
      architecture: "x64",
      configuration: "Release",
      sdkVersion: "3.8.1",
      sdkCommit: "3cdf9ca5d1f5b1b21e0a86832aa4abe55607bd96",
    };
  }
  if (!nativeVst3Scanner) throw new Error("Candidates require the exact EdmgStudio.Vst3Scanner.exe payload.");
  const packageJson = JSON.parse(await fsp.readFile(path.join(studioRoot, "package.json"), "utf8"));
  const epoch = sourceDateEpoch || process.env.SOURCE_DATE_EPOCH || git(repoRoot, ["show", "-s", "--format=%ct", gitState.commitSha]).trim();
  if (!/^\d+$/.test(String(epoch))) throw new Error("SOURCE_DATE_EPOCH must be an integer Unix timestamp.");
  const identity = storeMetadata ? {
    kind: "store", name: storeMetadata.identityName, publisher: storeMetadata.publisher,
    version: storeMetadata.version, displayName: storeMetadata.displayName,
    publisherDisplayName: storeMetadata.publisherDisplayName,
  } : {
    kind: mode === "production" ? "sideload" : "development",
    name: packageIdentity?.name,
    publisher: packageIdentity?.publisher,
    version: packageIdentity?.version || packageJson.version,
    applicationId: packageIdentity?.applicationId,
  };
  if ([identity.name, identity.publisher, identity.version].some((item) => !String(item || "").trim())) {
    throw new Error("Candidate requires the effective MSIX name, publisher, and version.");
  }
  const core = {
    schemaVersion: CANDIDATE_SCHEMA_VERSION,
    policy: { mode, distributable: false, storeSubmissionReady: false },
    source: { ...gitState, timestampPolicy: "SOURCE_DATE_EPOCH-or-commit-time", sourceDateEpoch: Number(epoch) },
    target: { os: "windows", architecture: "x64" },
    product: { name: packageJson.build?.productName || "EDMG Studio", version: packageJson.version, identity },
    tools: {
      node: process.version, git: toolVersion("git", ["--version"]), dotnet: toolVersion("dotnet", ["--version"]),
      powershell: toolVersion("powershell", ["-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"]),
      uv: toolVersion(process.env.EDMG_UV || "uv", ["--version"]), pnpm: toolVersion("pnpm", ["--version"]),
    },
    inputs,
    backend,
    nativeVst3Host,
    nativeVst3Scanner,
  };
  const candidateId = `edmg-rc1-${sha256Bytes(stableJson(core))}`;
  return {
    schemaVersion: CANDIDATE_SCHEMA_VERSION, candidateId, candidateCore: core,
    finalizedAt: null,
    artifacts: { msix: null, installer: null },
    lifecycleArtifacts: { install: null, upgrade: null, rollback: null },
    evidence: { signing: null, timestamp: null, sbom: null, checksums: null, lifecycle: null, storeCertification: null },
  };
}

export function assertCandidate(document, { requireMode = "", requireBackend = false } = {}) {
  if (document?.schemaVersion !== CANDIDATE_SCHEMA_VERSION || !/^edmg-rc1-[a-f0-9]{64}$/.test(document?.candidateId || "")) {
    throw new Error("Invalid release candidate manifest schema or candidate ID.");
  }
  const expected = `edmg-rc1-${sha256Bytes(stableJson(document.candidateCore))}`;
  if (document.candidateId !== expected) throw new Error("Release candidate core was modified after candidate ID generation.");
  if (document.candidateCore.target.architecture !== "x64") throw new Error("Only x64 release candidates are supported.");
  if (requireMode && document.candidateCore.policy.mode !== requireMode) throw new Error(`Expected ${requireMode} candidate mode.`);
  if (requireBackend && !document.candidateCore.backend) throw new Error("Candidate does not bind a backend payload.");
  return document;
}

export async function verifyBackendCandidate(document, backendManifestPath) {
  assertCandidate(document, { requireBackend: true });
  const manifest = JSON.parse(await fsp.readFile(backendManifestPath, "utf8"));
  if (manifest.releaseCandidateId !== document.candidateId) throw new Error("Backend release candidate ID does not match candidate manifest.");
  const actual = backendPayloadIdentity(manifest);
  if (stableJson(actual) !== stableJson(document.candidateCore.backend)) throw new Error("Backend payload identity does not match candidate manifest.");
  return true;
}

export async function attachArtifact(document, kind, filePath, metadata = {}) {
  assertCandidate(document);
  if (!["msix", "installer"].includes(kind)) throw new Error(`Unsupported candidate artifact: ${kind}`);
  const stat = await fsp.stat(filePath);
  const artifact = { fileName: path.basename(filePath), bytes: stat.size, sha256: await sha256File(filePath), ...metadata };
  document.artifacts[kind] = artifact;
  document.finalizedAt = new Date().toISOString();
  return artifact;
}

export function assertArtifact(document, kind, candidateId, sha256) {
  assertCandidate(document);
  if (candidateId !== document.candidateId) throw new Error(`${kind} candidate ID mismatch.`);
  if (!document.artifacts[kind] || document.artifacts[kind].sha256 !== sha256) throw new Error(`${kind} hash mismatch.`);
  return true;
}

export function validatePackageContract({ candidate, msixMetadata, installerMetadata = null }) {
  assertCandidate(candidate, { requireBackend: true });
  assertArtifact(candidate, "msix", msixMetadata?.candidateId, msixMetadata?.package?.sha256);
  if (stableJson(msixMetadata.backend) !== stableJson(candidate.candidateCore.backend)) throw new Error("MSIX backend payload identity mismatch.");
  if (candidate.candidateCore.nativeVst3Host && stableJson(msixMetadata.nativeVst3Host) !== stableJson(candidate.candidateCore.nativeVst3Host)) {
    throw new Error("MSIX native VST3 host identity mismatch.");
  }
  if (candidate.candidateCore.nativeVst3Scanner && stableJson(msixMetadata.nativeVst3Scanner) !== stableJson(candidate.candidateCore.nativeVst3Scanner)) {
    throw new Error("MSIX native VST3 scanner identity mismatch.");
  }
  const identity = candidate.candidateCore.product.identity;
  for (const key of ["name", "publisher", "version"]) {
    if (msixMetadata.package?.[key] !== identity[key]) throw new Error(`MSIX ${key} identity mismatch.`);
  }
  if (installerMetadata) {
    assertArtifact(candidate, "installer", installerMetadata.candidateId, installerMetadata.sha256);
    if (installerMetadata.msixSha256 !== candidate.artifacts.msix.sha256) throw new Error("Installer MSIX hash mismatch.");
    if (stableJson(installerMetadata.backend) !== stableJson(candidate.candidateCore.backend)) throw new Error("Installer backend payload identity mismatch.");
  }
  return true;
}

export async function attachEvidenceReference(document, kind, reference) {
  assertCandidate(document);
  if (!Object.hasOwn(document.evidence, kind)) throw new Error(`Unsupported candidate evidence kind: ${kind}`);
  if (isPlaceholder(reference)) throw new Error(`${kind} evidence reference is missing or placeholder.`);
  const evidencePath = path.resolve(reference);
  const stat = await fsp.stat(evidencePath);
  if (!stat.isFile()) throw new Error(`${kind} evidence reference is not a file.`);
  document.evidence[kind] = {
    reference: evidencePath.replaceAll("\\", "/"),
    bytes: stat.size,
    sha256: await sha256File(evidencePath),
  };
  return document.evidence[kind];
}

export async function attachLifecycleArtifact(document, role, filePath, metadata = {}) {
  assertCandidate(document);
  if (!["install", "upgrade", "rollback"].includes(role)) throw new Error(`Unsupported lifecycle artifact role: ${role}`);
  const identity = metadata.identity;
  if (!identity || ["name", "publisher", "version"].some((key) => !String(identity[key] || "").trim())) {
    throw new Error("Lifecycle artifacts require exact name, publisher, and version metadata.");
  }
  const stat = await fsp.stat(filePath);
  document.lifecycleArtifacts ||= { install: null, upgrade: null, rollback: null };
  document.lifecycleArtifacts[role] = {
    fileName: path.basename(filePath), bytes: stat.size, sha256: await sha256File(filePath),
    identity: { name: identity.name, publisher: identity.publisher, version: identity.version, architecture: "x64" },
  };
  return document.lifecycleArtifacts[role];
}

function assertEvidenceBinding(binding, kind) {
  if (!binding || isPlaceholder(binding.reference) || !Number.isSafeInteger(binding.bytes) || binding.bytes <= 0 || !HEX64.test(binding.sha256 || "")) {
    throw new Error(`${kind} evidence binding is invalid.`);
  }
}

export async function verifyWindowsArtifactAuthenticity({
  artifactPaths,
  platform = process.platform,
  env = process.env,
  studioRoot,
  execFileImpl = execFileAsync,
}) {
  if (platform !== "win32") {
    throw new Error("Production Authenticode verification requires a Windows host.");
  }
  const verifier = path.join(studioRoot, "packaging", "windows", "verify_artifact_signatures.ps1");
  if (!fs.existsSync(verifier)) throw new Error("Windows Authenticode verifier is missing.");
  for (const [kind, artifactPath] of Object.entries(artifactPaths || {})) {
    if (!artifactPath) throw new Error(`Production Authenticode verification requires ${kind}.`);
    const args = [
      "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", verifier,
      "-ArtifactPaths", path.resolve(artifactPath),
    ];
    try {
      await execFileImpl("powershell.exe", args, { env, windowsHide: true, shell: false });
    } catch (error) {
      throw new Error(`Independent ${kind} Authenticode verification failed: ${error?.stderr || error?.message || error}`);
    }
  }
  return true;
}

export async function verifyProductionCandidate({ candidate, artifactPaths, evidencePaths, now = new Date(), maxEvidenceAgeMs = 30 * 24 * 60 * 60 * 1000, artifactVerifier = verifyWindowsArtifactAuthenticity, platform = process.platform, env = process.env, studioRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..") }) {
  assertCandidate(candidate, { requireMode: "production", requireBackend: true });
  if (candidate.candidateCore.source.dirty) throw new Error("Production verification requires a clean production candidate.");
  for (const kind of ["msix", "installer"]) {
    const supplied = artifactPaths?.[kind];
    if (!supplied) throw new Error(`Production verification requires --${kind}.`);
    const bound = candidate.artifacts?.[kind];
    if (!bound || !HEX64.test(bound.sha256 || "") || !Number.isSafeInteger(bound.bytes) || bound.bytes <= 0) throw new Error(`Production candidate is missing valid ${kind} binding.`);
    const stat = await fsp.stat(supplied).catch(() => { throw new Error(`${kind} artifact is missing.`); });
    if (!stat.isFile() || stat.size !== bound.bytes || await sha256File(supplied) !== bound.sha256 || path.basename(supplied) !== bound.fileName) {
      throw new Error(`${kind} path/hash/size does not match candidate manifest.`);
    }
  }
  await artifactVerifier({ artifactPaths, platform, env, studioRoot });
  for (const kind of ["signing", "timestamp"]) {
    assertEvidenceBinding(candidate.evidence?.[kind], kind);
    const supplied = evidencePaths?.[kind];
    if (!supplied) throw new Error(`Production verification requires --${kind}-evidence.`);
    if (path.resolve(supplied) !== path.resolve(candidate.evidence[kind].reference)) throw new Error(`${kind} evidence path does not match the candidate reference.`);
    const stat = await fsp.stat(supplied).catch(() => { throw new Error(`${kind} evidence is missing.`); });
    if (!stat.isFile() || stat.size !== candidate.evidence[kind].bytes || await sha256File(supplied) !== candidate.evidence[kind].sha256) {
      throw new Error(`${kind} evidence hash/size mismatch.`);
    }
  }
  const signing = JSON.parse(await fsp.readFile(evidencePaths.signing, "utf8"));
  if (signing?.schemaVersion !== 1 || !Array.isArray(signing.runs)) throw new Error("Signing evidence schema is invalid.");
  const run = [...signing.runs].reverse().find((item) => item?.candidateId === candidate.candidateId);
  if (!run || run.ok !== true || !run.required || !run.completedAt) throw new Error("No successful required signing run matches this candidate.");
  const completedAt = Date.parse(run.completedAt);
  const finalizedAt = Date.parse(candidate.finalizedAt || "");
  if (!Number.isFinite(completedAt) || now.getTime() - completedAt > maxEvidenceAgeMs) throw new Error("Signing evidence is stale.");
  const records = Array.isArray(run.artifacts) ? run.artifacts : [];
  for (const kind of ["msix", "installer"]) {
    const bound = candidate.artifacts[kind];
    const record = records.find((item) => item.sha256 === bound.sha256 && item.bytes === bound.bytes);
    if (!record) throw new Error(`Signing evidence does not bind the ${kind} artifact hash and size.`);
    if (record.authenticodeStatus !== "Valid" || record.signToolVerified !== true || record.timestampVerified !== true) throw new Error(`${kind} signing or trusted timestamp verification failed.`);
    const actual = String(record.signerThumbprint || "").replaceAll(" ", "").toUpperCase();
    const expected = String(record.expectedSignerThumbprint || run.expectedSignerThumbprint || "").replaceAll(" ", "").toUpperCase();
    if (!/^[A-F0-9]{40}$/.test(actual) || actual !== expected || !String(record.signerSubject || "").trim()) throw new Error(`${kind} signer identity is missing or mismatched.`);
  }
  const timestamp = JSON.parse(await fsp.readFile(evidencePaths.timestamp, "utf8"));
  if (timestamp?.schemaVersion !== 1 || timestamp.candidateId !== candidate.candidateId || timestamp.status !== "trusted" || timestamp.signingEvidenceSha256 !== candidate.evidence.signing.sha256 || !timestamp.verifiedAt) {
    throw new Error("Trusted timestamp evidence is invalid or does not bind the signing evidence.");
  }
  const verifiedAt = Date.parse(timestamp.verifiedAt);
  if (!Number.isFinite(verifiedAt) || now.getTime() - verifiedAt > maxEvidenceAgeMs) throw new Error("Timestamp evidence is stale.");
  return true;
}

export function isPlaceholder(value) {
  return typeof value !== "string" || !value.trim() || /(?:<|>|placeholder|replace|example|todo|xxxx|00000000-0000)/i.test(value);
}
