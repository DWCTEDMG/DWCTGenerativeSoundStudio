import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

export const REQUIRED_LIFECYCLE_RECEIPTS = ["cleanInstall", "firstRunNativeFlow", "projectPersistence", "autosaveRecovery", "upgrade", "repair", "rollback", "uninstall"];
const INTERACTIVE = ["firstRunNativeFlow", "projectPersistence", "autosaveRecovery"];
const HEX64 = /^[a-f0-9]{64}$/;
const sameIdentity = (a, b) => ["name", "publisher", "version", "architecture"].every((key) => String(a?.[key] || "").toLowerCase() === String(b?.[key] || "").toLowerCase());

export function validateLifecycleEvidence(document, { requirePassed = false, expectedCandidateId = "", now = new Date(), maxReceiptAgeMs = 30 * 24 * 60 * 60 * 1000 } = {}) {
  if (document?.schemaVersion !== 4) throw new Error("Lifecycle evidence schemaVersion must be 4.");
  if (!/^edmg-rc1-[a-f0-9]{64}$/.test(document.candidateId || "")) throw new Error("Lifecycle evidence requires a candidate ID.");
  if (expectedCandidateId && document.candidateId !== expectedCandidateId) throw new Error("Lifecycle candidate ID mismatch.");
  if (!document.packageIdentity || document.packageIdentity.architecture !== "x64" || ["name", "publisher", "version"].some((key) => !String(document.packageIdentity[key] || "").trim())) throw new Error("Lifecycle package identity is invalid.");
  if (!["retain", "remove"].includes(document.dataPolicy)) throw new Error("Lifecycle dataPolicy must be retain or remove.");
  if (!document.artifacts) throw new Error("Lifecycle evidence requires artifact bindings.");
  const requiredRoles = document.scenario === "Full" ? ["install", "upgrade", "rollback"] : ({ CleanInstall: ["install"], Upgrade: ["upgrade"], Rollback: ["rollback"] }[document.scenario] || []);
  for (const role of requiredRoles) if (!document.artifacts[role]) throw new Error(`Lifecycle ${role} artifact binding is required for ${document.scenario}.`);
  if (document.scenario === "Full" && (!document.candidateArtifact || document.candidateArtifact.sha256 !== document.artifacts.upgrade?.sha256)) throw new Error("Full lifecycle candidateArtifact must explicitly match the post-upgrade package.");
  for (const [role, artifact] of Object.entries(document.artifacts)) {
    if (artifact && (!HEX64.test(artifact.sha256 || "") || !Number.isSafeInteger(artifact.bytes) || artifact.bytes <= 0 || !artifact.identity || artifact.identity.architecture !== "x64")) throw new Error(`Lifecycle ${role} artifact binding is invalid.`);
  }
  for (const name of REQUIRED_LIFECYCLE_RECEIPTS) {
    const receipt = document.receipts?.[name];
    if (!receipt || !["not-run", "passed", "failed"].includes(receipt.status)) throw new Error(`Lifecycle receipt ${name} is missing or invalid.`);
    if (receipt.status === "passed" && (!receipt.observedAt || !receipt.evidence)) throw new Error(`Passed lifecycle receipt ${name} requires observedAt and evidence.`);
  }
  if (INTERACTIVE.some((name) => document.receipts[name].status === "passed")) {
    const imported = document.interactiveReceipt;
    if (!imported || imported.candidateId !== document.candidateId || !HEX64.test(imported.testedPackageSha256 || "") || !sameIdentity(imported.packageIdentity, (document.scenario === "Full" ? document.artifacts.upgrade : document.artifacts.install)?.identity) || !imported.executedAt || !imported.evidenceReference || !HEX64.test(imported.evidenceSha256 || "")) throw new Error("Imported interactive receipt provenance is missing or mismatched.");
    if (imported.testedPackageSha256 !== (document.scenario === "Full" ? document.artifacts.upgrade : document.artifacts.install)?.sha256) throw new Error("Interactive receipt tested package hash mismatch.");
    const executedAt = Date.parse(imported.executedAt);
    if (!Number.isFinite(executedAt) || executedAt > now.getTime() + 5 * 60 * 1000 || now.getTime() - executedAt > maxReceiptAgeMs) throw new Error("Interactive receipt is stale or has an invalid execution timestamp.");
  }
  if (requirePassed && (document.status !== "passed" || REQUIRED_LIFECYCLE_RECEIPTS.some((name) => document.receipts[name].status !== "passed"))) throw new Error("Lifecycle qualification is incomplete; every required receipt must have explicit passed evidence.");
  return document;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const input = process.argv[2];
  if (!input) throw new Error("Usage: node validate-lifecycle-evidence.mjs <evidence.json> [--require-passed] [--candidate-id ID]");
  const expectedIndex = process.argv.indexOf("--candidate-id");
  const document = JSON.parse(fs.readFileSync(path.resolve(input), "utf8"));
  validateLifecycleEvidence(document, { requirePassed: process.argv.includes("--require-passed"), expectedCandidateId: expectedIndex >= 0 ? process.argv[expectedIndex + 1] : "" });
  if (document.interactiveReceipt) {
    const reference = path.resolve(path.dirname(path.resolve(input)), document.interactiveReceipt.evidenceReference);
    if (!fs.statSync(reference).isFile()) throw new Error("Interactive immutable evidence reference is missing.");
    const hash = crypto.createHash("sha256").update(fs.readFileSync(reference)).digest("hex");
    if (hash !== document.interactiveReceipt.evidenceSha256) throw new Error("Interactive immutable evidence hash mismatch.");
  }
  console.log(JSON.stringify({ ok: true }, null, 2));
}
