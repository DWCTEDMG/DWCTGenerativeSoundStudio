import assert from "node:assert/strict";
import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { assertArtifact, assertCandidate, attachArtifact, backendPayloadIdentity, createCandidate, sha256Bytes, stableJson, validatePackageContract, verifyProductionCandidate } from "./release-candidate-lib.mjs";
import { validateLifecycleEvidence } from "./validate-lifecycle-evidence.mjs";
import { validateStoreSubmission } from "./validate-store-submission.mjs";

const studioRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const scratch = path.join(studioRoot, ".cache", "gate-f-tests");
const id = `edmg-rc1-${"a".repeat(64)}`;
function candidate() {
  const backend = { sourceSha256: "1".repeat(64), payloadTreeSha256: "2".repeat(64), binarySha256: "3".repeat(64) };
  const identity = { name: "EDMG.Studio", publisher: "CN=EDMG", version: "1.2.0.0" };
  const candidateCore = { policy: { mode: "developer" }, target: { architecture: "x64" }, product: { identity }, backend };
  return { schemaVersion: 1, candidateId: `edmg-rc1-${sha256Bytes(stableJson(candidateCore))}`, candidateCore, artifacts: { msix: null, installer: null }, evidence: { signing: null } };
}

test("candidate core and artifact tampering fail closed", async () => {
  await fsp.mkdir(scratch, { recursive: true });
  const artifact = path.join(scratch, "candidate.msix");
  await fsp.writeFile(artifact, "original", "utf8");
  const value = candidate();
  await attachArtifact(value, "msix", artifact, { candidateId: value.candidateId });
  assertCandidate(value);
  assertArtifact(value, "msix", value.candidateId, value.artifacts.msix.sha256);
  assert.throws(() => assertArtifact(value, "msix", id, value.artifacts.msix.sha256), /candidate ID mismatch/);
  value.candidateCore.target.architecture = "arm64";
  assert.throws(() => assertCandidate(value), /modified/);
  await fsp.rm(scratch, { recursive: true, force: true });
});

test("candidate creation hashes repository-pinned build inputs and exact native VST3 executables", async () => {
  await fsp.mkdir(scratch, { recursive: true });
  const vst3HostPath = path.join(scratch, "EdmgStudio.Vst3Host.exe");
  const vst3ScannerPath = path.join(scratch, "EdmgStudio.Vst3Scanner.exe");
  await fsp.writeFile(vst3HostPath, "native host fixture", "utf8");
  await fsp.writeFile(vst3ScannerPath, "native scanner fixture", "utf8");
  const value = await createCandidate({
    repoRoot: path.resolve(studioRoot, "..", ".."),
    studioRoot,
    vst3HostPath,
    vst3ScannerPath,
    packageIdentity: { name: "EDMG.Studio", publisher: "CN=EDMG", version: "1.2.0.0", applicationId: "App" },
  });
  assertCandidate(value);
  assert.ok(value.candidateCore.inputs.some((input) => input.path === "studio/edmg-studio-winui/global.json"));
  assert.ok(value.candidateCore.inputs.some((input) => input.path === "studio/edmg-studio-winui/native/vst3-host/src/main.cpp"));
  assert.equal(value.candidateCore.nativeVst3Host.sha256, await (await import("./release-candidate-lib.mjs")).sha256File(vst3HostPath));
  assert.equal(value.candidateCore.nativeVst3Host.sdkVersion, "3.8.1");
  assert.equal(value.candidateCore.nativeVst3Host.sdkCommit, "3cdf9ca5d1f5b1b21e0a86832aa4abe55607bd96");
  assert.equal(value.candidateCore.nativeVst3Scanner.sha256, await (await import("./release-candidate-lib.mjs")).sha256File(vst3ScannerPath));
  assert.equal(value.candidateCore.nativeVst3Scanner.fileName, "EdmgStudio.Vst3Scanner.exe");
  await fsp.rm(scratch, { recursive: true, force: true });
});

test("candidate creation fails closed without both native VST3 executables", async () => {
  await assert.rejects(() => createCandidate({
    repoRoot: path.resolve(studioRoot, "..", ".."),
    studioRoot,
    packageIdentity: { name: "EDMG.Studio", publisher: "CN=EDMG", version: "1.2.0.0", applicationId: "App" },
  }), /exact EdmgStudio\.Vst3Host\.exe/);
  await fsp.mkdir(scratch, { recursive: true });
  const vst3HostPath = path.join(scratch, "EdmgStudio.Vst3Host.exe");
  await fsp.writeFile(vst3HostPath, "native host fixture", "utf8");
  await assert.rejects(() => createCandidate({
    repoRoot: path.resolve(studioRoot, "..", ".."),
    studioRoot,
    vst3HostPath,
    packageIdentity: { name: "EDMG.Studio", publisher: "CN=EDMG", version: "1.2.0.0", applicationId: "App" },
  }), /exact EdmgStudio\.Vst3Scanner\.exe/);
  await fsp.rm(scratch, { recursive: true, force: true });
});

test("backend payload identity changes when an inventoried hash changes", () => {
  const manifest = { sourceHash: "1".repeat(64), sourceFileCount: 1, binarySha256: "2".repeat(64), acceleratorProfile: "directml", lockSha256: "3".repeat(64), bundleEntries: [{ type: "file", path: "a", size: 1, sha256: "4".repeat(64) }] };
  const before = backendPayloadIdentity(manifest);
  manifest.bundleEntries[0].sha256 = "5".repeat(64);
  assert.notEqual(backendPayloadIdentity(manifest).payloadTreeSha256, before.payloadTreeSha256);
});

test("package and installer contracts reject candidate, backend, and hash mismatches", () => {
  const value = candidate();
  value.candidateCore.nativeVst3Host = { sha256: "8".repeat(64), bytes: 1024 };
  value.candidateCore.nativeVst3Scanner = { sha256: "7".repeat(64), bytes: 512 };
  value.candidateId = `edmg-rc1-${sha256Bytes(stableJson(value.candidateCore))}`;
  value.artifacts.msix = { sha256: "4".repeat(64) };
  value.artifacts.installer = { sha256: "5".repeat(64) };
  const msix = { candidateId: value.candidateId, backend: value.candidateCore.backend, nativeVst3Host: value.candidateCore.nativeVst3Host, nativeVst3Scanner: value.candidateCore.nativeVst3Scanner, package: { ...value.candidateCore.product.identity, sha256: value.artifacts.msix.sha256 } };
  const installer = { candidateId: value.candidateId, backend: value.candidateCore.backend, sha256: value.artifacts.installer.sha256, msixSha256: value.artifacts.msix.sha256 };
  validatePackageContract({ candidate: value, msixMetadata: msix, installerMetadata: installer });
  assert.throws(() => validatePackageContract({ candidate: value, msixMetadata: { ...msix, candidateId: id } }), /candidate ID mismatch/);
  assert.throws(() => validatePackageContract({ candidate: value, msixMetadata: { ...msix, backend: { ...msix.backend, binarySha256: "6".repeat(64) } } }), /backend payload identity mismatch/);
  assert.throws(() => validatePackageContract({ candidate: value, msixMetadata: { ...msix, nativeVst3Host: { ...msix.nativeVst3Host, sha256: "9".repeat(64) } } }), /native VST3 host identity mismatch/);
  assert.throws(() => validatePackageContract({ candidate: value, msixMetadata: { ...msix, nativeVst3Scanner: { ...msix.nativeVst3Scanner, sha256: "9".repeat(64) } } }), /native VST3 scanner identity mismatch/);
  assert.throws(() => validatePackageContract({ candidate: value, msixMetadata: msix, installerMetadata: { ...installer, msixSha256: "7".repeat(64) } }), /Installer MSIX hash mismatch/);
});

test("lifecycle evidence never treats unrun checks as passed", () => {
  const receipts = Object.fromEntries(["cleanInstall", "firstRunNativeFlow", "projectPersistence", "autosaveRecovery", "upgrade", "repair", "rollback", "uninstall"].map((name) => [name, { status: "not-run", evidence: "", observedAt: null }]));
  const identity = { name: "EDMG.Studio", publisher: "CN=EDMG", version: "1.2.0.0", architecture: "x64" };
  const evidence = { schemaVersion: 4, candidateId: id, packageIdentity: identity, artifacts: { install: { fileName: "app.msix", bytes: 1, sha256: "1".repeat(64), identity }, upgrade: null, rollback: null }, dataPolicy: "retain", scenario: "CleanInstall", status: "incomplete", receipts };
  validateLifecycleEvidence(evidence);
  assert.throws(() => validateLifecycleEvidence(evidence, { requirePassed: true }), /incomplete/);
});

test("interactive receipts reject missing provenance, stale execution, and package mismatch", () => {
  const identity = { name: "EDMG.Studio", publisher: "CN=EDMG", version: "1.2.0.0", architecture: "x64" };
  const receipts = Object.fromEntries(["cleanInstall", "firstRunNativeFlow", "projectPersistence", "autosaveRecovery", "upgrade", "repair", "rollback", "uninstall"].map((name) => [name, { status: name === "firstRunNativeFlow" ? "passed" : "not-run", evidence: name, observedAt: name === "firstRunNativeFlow" ? "2026-09-15T00:00:00Z" : null }]));
  const base = { schemaVersion: 4, candidateId: id, packageIdentity: identity, artifacts: { install: { fileName: "app.msix", bytes: 1, sha256: "1".repeat(64), identity }, upgrade: null, rollback: null }, dataPolicy: "retain", scenario: "CleanInstall", status: "incomplete", receipts };
  assert.throws(() => validateLifecycleEvidence(base), /provenance/);
  const provenance = { candidateId: id, testedPackageSha256: "1".repeat(64), packageIdentity: identity, executedAt: "2026-09-15T00:00:00Z", evidenceReference: "session.json", evidenceSha256: "2".repeat(64) };
  assert.throws(() => validateLifecycleEvidence({ ...base, interactiveReceipt: { ...provenance, testedPackageSha256: "3".repeat(64) } }, { now: new Date("2026-09-15T01:00:00Z") }), /hash mismatch/);
  assert.throws(() => validateLifecycleEvidence({ ...base, interactiveReceipt: { ...provenance, executedAt: "2020-01-01T00:00:00Z" } }, { now: new Date("2026-09-15T01:00:00Z") }), /stale/);
});

test("production verification rejects forged, stale, failed, mismatched and missing evidence", async () => {
  await fsp.mkdir(scratch, { recursive: true });
  const msix = path.join(scratch, "app.msix"), installer = path.join(scratch, "setup.exe"), signingPath = path.join(scratch, "signing.json"), timestampPath = path.join(scratch, "timestamp.json");
  await fsp.writeFile(msix, "msix"); await fsp.writeFile(installer, "installer");
  const value = candidate(); value.candidateCore.policy.mode = "production"; value.candidateCore.source = { dirty: false }; value.candidateId = `edmg-rc1-${sha256Bytes(stableJson(value.candidateCore))}`;
  await attachArtifact(value, "msix", msix); await attachArtifact(value, "installer", installer);
  const thumb = "A".repeat(40), completedAt = "2026-09-15T00:00:00Z";
  const record = (kind) => ({ path: path.basename(kind === "msix" ? msix : installer), ...value.artifacts[kind], authenticodeStatus: "Valid", signToolVerified: true, timestampVerified: true, signerSubject: "CN=EDMG", signerThumbprint: thumb, expectedSignerThumbprint: thumb });
  await fsp.writeFile(signingPath, JSON.stringify({ schemaVersion: 1, runs: [{ candidateId: value.candidateId, required: true, ok: true, completedAt, expectedSignerThumbprint: thumb, artifacts: [record("msix"), record("installer")] }] }));
  value.finalizedAt = "2026-09-14T00:00:00Z"; value.evidence = {};
  const bind = async (kind, file) => { const stat = await fsp.stat(file); value.evidence[kind] = { reference: file, bytes: stat.size, sha256: await (await import("./release-candidate-lib.mjs")).sha256File(file) }; };
  await bind("signing", signingPath); await fsp.writeFile(timestampPath, JSON.stringify({ schemaVersion: 1, candidateId: value.candidateId, status: "trusted", signingEvidenceSha256: value.evidence.signing.sha256, verifiedAt: completedAt })); await bind("timestamp", timestampPath);
  let verificationCalls = 0;
  const artifactVerifier = async ({ artifactPaths }) => { verificationCalls++; assert.deepEqual(Object.keys(artifactPaths).sort(), ["installer", "msix"]); };
  const options = { candidate: value, artifactPaths: { msix, installer }, evidencePaths: { signing: signingPath, timestamp: timestampPath }, now: new Date("2026-09-15T01:00:00Z"), artifactVerifier };
  await verifyProductionCandidate(options);
  assert.equal(verificationCalls, 1);
  await assert.rejects(() => verifyProductionCandidate({ ...options, artifactPaths: { msix: path.join(scratch, "missing.msix"), installer } }), /missing/);
  const forged = structuredClone(value); forged.evidence.signing.sha256 = "f".repeat(64); await assert.rejects(() => verifyProductionCandidate({ ...options, candidate: forged }), /hash\/size mismatch/);
  const stale = structuredClone(value); stale.evidence = value.evidence; await assert.rejects(() => verifyProductionCandidate({ ...options, candidate: stale, now: new Date("2027-01-01T00:00:00Z") }), /stale/);
  const failedSigning = JSON.parse(await fsp.readFile(signingPath, "utf8")); failedSigning.runs[0].ok = false; await fsp.writeFile(signingPath, JSON.stringify(failedSigning));
  const failed = structuredClone(value); const failedStat = await fsp.stat(signingPath); failed.evidence.signing = { reference: signingPath, bytes: failedStat.size, sha256: await (await import("./release-candidate-lib.mjs")).sha256File(signingPath) };
  await assert.rejects(() => verifyProductionCandidate({ ...options, candidate: failed }), /successful required signing run/);
  await fsp.writeFile(msix, "tampered"); await assert.rejects(() => verifyProductionCandidate(options), /path\/hash\/size/);
  await fsp.rm(scratch, { recursive: true, force: true });
});

test("Store placeholders and unreturned certification are rejected", () => {
  const example = JSON.parse(fs.readFileSync(path.join(studioRoot, "..", "edmg-studio-winui", "StoreSubmission.example.json"), "utf8"));
  assert.throws(() => validateStoreSubmission(example), /placeholder/);
  const actual = { schemaVersion: 1, productId: "9ABC", identityName: "Vendor.App", publisher: "CN=ABC", publisherId: "ABC", version: "1.2.3.0", displayName: "EDMG Studio", publisherDisplayName: "Dwct", certification: { status: "pending", evidenceReference: "partner-center/submission-1" }, knownIssues: { status: "reviewed", evidenceReference: "docs/KNOWN_ISSUES.md" }, rollback: { status: "validated", evidenceReference: "evidence/rollback.json" } };
  validateStoreSubmission(actual);
  assert.throws(() => validateStoreSubmission(actual, { production: true }), /certification/);
});
