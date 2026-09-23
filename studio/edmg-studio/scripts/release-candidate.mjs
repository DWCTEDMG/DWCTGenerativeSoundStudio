import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  assertCandidate,
  attachArtifact,
  attachEvidenceReference,
  attachLifecycleArtifact,
  createCandidate,
  sha256File,
  validatePackageContract,
  verifyBackendCandidate,
  verifyProductionCandidate,
} from "./release-candidate-lib.mjs";

const studioRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(studioRoot, "..", "..");
const defaultManifest = path.join(studioRoot, "release", "candidate", "release-candidate.json");
const args = process.argv.slice(2);
const command = args.shift() || "verify";
const value = (name, fallback = "") => {
  const index = args.indexOf(name);
  return index < 0 ? fallback : args[index + 1];
};
const flag = (name) => args.includes(name);
const manifestPath = path.resolve(value("--manifest", defaultManifest));

async function readCandidate() {
  return assertCandidate(JSON.parse(await fsp.readFile(manifestPath, "utf8")));
}
async function writeCandidate(candidate) {
  await fsp.mkdir(path.dirname(manifestPath), { recursive: true });
  await fsp.writeFile(manifestPath, `${JSON.stringify(candidate, null, 2)}\n`, "utf8");
}

if (command === "create") {
  const mode = value("--mode", "developer");
  const backendManifestPath = value("--backend-manifest");
  const vst3HostPath = value("--vst3-host");
  const vst3ScannerPath = value("--vst3-scanner");
  if (!vst3HostPath) throw new Error("create requires --vst3-host <EdmgStudio.Vst3Host.exe>.");
  if (!vst3ScannerPath) throw new Error("create requires --vst3-scanner <EdmgStudio.Vst3Scanner.exe>.");
  const storePath = value("--store-metadata");
  const storeMetadata = storePath ? JSON.parse(await fsp.readFile(path.resolve(storePath), "utf8")) : null;
  const candidate = await createCandidate({
    repoRoot, studioRoot, mode, storeMetadata,
    packageIdentity: storeMetadata ? null : {
      name: value("--package-name"), publisher: value("--package-publisher"),
      version: value("--package-version"), applicationId: value("--application-id"),
    },
    backendManifestPath: backendManifestPath ? path.resolve(backendManifestPath) : "",
    vst3HostPath: path.resolve(vst3HostPath),
    vst3ScannerPath: path.resolve(vst3ScannerPath),
    sourceDateEpoch: value("--source-date-epoch"),
  });
  await writeCandidate(candidate);
  console.log(JSON.stringify({ ok: true, candidateId: candidate.candidateId, manifestPath, distributable: candidate.candidateCore.policy.distributable }, null, 2));
} else if (command === "bind-backend") {
  const candidate = await readCandidate();
  const backendPath = path.resolve(value("--backend-manifest"));
  const backend = JSON.parse(await fsp.readFile(backendPath, "utf8"));
  backend.releaseCandidateId = candidate.candidateId;
  await fsp.writeFile(backendPath, `${JSON.stringify(backend, null, 2)}\n`, "utf8");
  await verifyBackendCandidate(candidate, backendPath);
  console.log(`[release-candidate] backend bound to ${candidate.candidateId}`);
} else if (command === "attach") {
  const candidate = await readCandidate();
  const kind = value("--kind");
  const artifactPath = path.resolve(value("--artifact"));
  const metadataPath = value("--metadata");
  const metadata = metadataPath && fs.existsSync(path.resolve(metadataPath))
    ? JSON.parse(await fsp.readFile(path.resolve(metadataPath), "utf8")) : {};
  const artifact = await attachArtifact(candidate, kind, artifactPath, metadata);
  await writeCandidate(candidate);
  console.log(JSON.stringify({ ok: true, candidateId: candidate.candidateId, kind, artifact }, null, 2));
} else if (command === "attach-evidence") {
  const candidate = await readCandidate();
  const kind = value("--kind");
  const reference = value("--reference");
  const evidence = await attachEvidenceReference(candidate, kind, reference);
  await writeCandidate(candidate);
  console.log(JSON.stringify({ ok: true, candidateId: candidate.candidateId, kind, evidence }, null, 2));
} else if (command === "attach-lifecycle") {
  const candidate = await readCandidate();
  const role = value("--role");
  const artifactPath = path.resolve(value("--artifact"));
  const identityPath = path.resolve(value("--identity"));
  const identity = JSON.parse(await fsp.readFile(identityPath, "utf8"));
  const artifact = await attachLifecycleArtifact(candidate, role, artifactPath, { identity });
  await writeCandidate(candidate);
  console.log(JSON.stringify({ ok: true, candidateId: candidate.candidateId, role, artifact }, null, 2));
} else if (command === "verify-package") {
  const candidate = await readCandidate();
  const metadataPath = path.resolve(value("--msix-metadata"));
  const installerPath = value("--installer-metadata");
  const msixMetadata = JSON.parse(await fsp.readFile(metadataPath, "utf8"));
  const installerMetadata = installerPath ? JSON.parse(await fsp.readFile(path.resolve(installerPath), "utf8")) : null;
  validatePackageContract({ candidate, msixMetadata, installerMetadata });
  console.log(JSON.stringify({ ok: true, candidateId: candidate.candidateId }, null, 2));
} else if (command === "verify") {
  const candidate = await readCandidate();
  const backendPath = value("--backend-manifest");
  if (backendPath) await verifyBackendCandidate(candidate, path.resolve(backendPath));
  for (const kind of ["msix", "installer"]) {
    const artifactPath = value(`--${kind}`);
    if (!artifactPath) continue;
    const bound = candidate.artifacts[kind];
    if (!bound || bound.sha256 !== await sha256File(path.resolve(artifactPath))) throw new Error(`${kind} bytes do not match candidate manifest.`);
  }
  if (flag("--production")) {
    await verifyProductionCandidate({
      candidate,
      artifactPaths: { msix: value("--msix"), installer: value("--installer") },
      evidencePaths: { signing: value("--signing-evidence"), timestamp: value("--timestamp-evidence") },
    });
  }
  console.log(JSON.stringify({ ok: true, candidateId: candidate.candidateId }, null, 2));
} else {
  throw new Error(`Unknown release-candidate command: ${command}`);
}
