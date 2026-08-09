import assert from "node:assert/strict";
import fs from "node:fs";
import fsp from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  buildChecksumManifest,
  collectReleaseArtifactPaths,
  planCodeSigning,
  readPythonSbom,
  readWindowsSignatureEvidence,
  resolveCodeSigningConfig,
  validateBundleEvidenceForSbomReuse,
  writeReleaseEvidence,
} from "./release-evidence-lib.mjs";
import { uvExportCycloneDxArgs } from "./release-python-toolchain.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const studioRoot = path.resolve(__dirname, "..");

test("uv CycloneDX export args mirror the frozen release profile", () => {
  assert.deepEqual(uvExportCycloneDxArgs("cpu").slice(0, 4), ["export", "--format", "cyclonedx1.5", "--frozen"]);
  assert.ok(uvExportCycloneDxArgs("directml").includes("--extra"));
  assert.ok(uvExportCycloneDxArgs("cuda").includes("--group"));
});

test("release artifact inventory keeps installer targets isolated", () => {
  const bundlePaths = collectReleaseArtifactPaths(studioRoot, "bundle");
  assert.ok(
    bundlePaths.some((filePath) => filePath.replaceAll("\\", "/").endsWith("python_backend/uv.lock")),
    "bundle inventory should include uv.lock when present",
  );

  const tempRoot = path.join(os.tmpdir(), `edmg-release-evidence-${process.pid}`);
  const distDir = path.join(tempRoot, "dist");
  const genericInnoDir = path.join(tempRoot, "dist-inno");
  const innoDir = path.join(tempRoot, "dist-inno-cuda");
  const genericPayloadDir = path.join(genericInnoDir, "payload");
  const payloadDir = path.join(innoDir, "payload");
  fs.mkdirSync(distDir, { recursive: true });
  fs.mkdirSync(genericPayloadDir, { recursive: true });
  fs.mkdirSync(payloadDir, { recursive: true });
  const installer = path.join(distDir, "EDMG-Studio-1.0.0-windows-x64-directml-Setup.exe");
  const appImage = path.join(distDir, "EDMG-Studio-1.0.0-linux-x64-cuda.AppImage");
  const genericInnoInstaller = path.join(
    genericInnoDir,
    "EDMG-Studio-1.0.0-windows-x64-directml-Setup.exe",
  );
  const genericPayload = path.join(genericPayloadDir, "win-unpacked.7z");
  const genericSidecar = path.join(genericPayloadDir, "payload-integrity.json");
  const innoInstaller = path.join(innoDir, "EDMG-Studio-1.0.0-windows-x64-cuda-Setup.exe");
  const payload = path.join(payloadDir, "win-unpacked.7z");
  const sidecar = path.join(payloadDir, "payload-integrity.json");
  fs.writeFileSync(installer, "installer");
  fs.writeFileSync(appImage, "appimage");
  fs.writeFileSync(genericInnoInstaller, "inno installer");
  fs.writeFileSync(genericPayload, "external payload");
  fs.writeFileSync(genericSidecar, "integrity sidecar");
  fs.writeFileSync(innoInstaller, "inno installer");
  fs.writeFileSync(payload, "external payload");
  fs.writeFileSync(sidecar, "integrity sidecar");
  try {
    assert.deepEqual(new Set(collectReleaseArtifactPaths(tempRoot, "dist", "win-nsis")), new Set([installer]));
    assert.deepEqual(new Set(collectReleaseArtifactPaths(tempRoot, "dist", "linux-appimage")), new Set([appImage]));
    assert.deepEqual(
      new Set(collectReleaseArtifactPaths(tempRoot, "dist", "win-inno")),
      new Set([genericInnoInstaller, genericPayload, genericSidecar]),
    );
    assert.deepEqual(
      new Set(collectReleaseArtifactPaths(tempRoot, "dist", "win-inno-cuda")),
      new Set([innoInstaller, payload, sidecar]),
    );
    assert.throws(() => collectReleaseArtifactPaths(tempRoot, "dist"), /artifact set is required/);
    assert.throws(() => collectReleaseArtifactPaths(tempRoot, "all", "win-nsis"), /Unsupported/);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test("checksum manifest records SHA-256 entries with self hash", async () => {
  const tempDir = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-release-checksum-"));
  const sample = path.join(tempDir, "sample.txt");
  await fsp.writeFile(sample, "release evidence\n", "utf8");
  try {
    const manifest = await buildChecksumManifest({
      root: tempDir,
      artifactPaths: [sample],
      metadata: { phase: "bundle", studioVersion: "1.0.0" },
    });
    assert.equal(manifest.artifacts.length, 1);
    assert.match(manifest.artifacts[0].sha256, /^[a-f0-9]{64}$/);
    assert.match(manifest.manifestSha256, /^[a-f0-9]{64}$/);
  } finally {
    await fsp.rm(tempDir, { recursive: true, force: true });
  }
});

test("existing CycloneDX SBOM can be reused without rewriting it", async () => {
  const tempDir = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-release-sbom-"));
  const sbomPath = path.join(tempDir, "python-backend-cuda.cyclonedx.json");
  const contents = JSON.stringify({
    bomFormat: "CycloneDX",
    specVersion: "1.5",
    metadata: {
      tools: { name: "uv", version: "0.11.28" },
      component: { name: "edmg-studio-backend", version: "1.2.0" },
    },
    components: [{ name: "torch" }, { name: "faster-whisper" }],
    dependencies: [],
  });
  await fsp.writeFile(sbomPath, contents, "utf8");
  try {
    const before = await fsp.readFile(sbomPath, "utf8");
    const summary = readPythonSbom({ profile: "cuda", outputPath: sbomPath, version: "1.2.0" });
    const after = await fsp.readFile(sbomPath, "utf8");

    assert.equal(summary.format, "CycloneDX");
    assert.equal(summary.version, "1.5");
    assert.equal(summary.componentCount, 2);
    assert.equal(summary.reusedExisting, true);
    assert.equal(after, before);
  } finally {
    await fsp.rm(tempDir, { recursive: true, force: true });
  }
});

test("existing SBOM reuse rejects missing and malformed evidence", async () => {
  const tempDir = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-release-sbom-invalid-"));
  const missingPath = path.join(tempDir, "missing.cyclonedx.json");
  const invalidPath = path.join(tempDir, "invalid.cyclonedx.json");
  await fsp.writeFile(invalidPath, JSON.stringify({ bomFormat: "not-cyclonedx" }), "utf8");
  try {
    assert.throws(
      () => readPythonSbom({ profile: "cuda", outputPath: missingPath }),
      /required but missing/,
    );
    assert.throws(
      () => readPythonSbom({ profile: "cuda", outputPath: invalidPath }),
      /not a valid CycloneDX/,
    );
  } finally {
    await fsp.rm(tempDir, { recursive: true, force: true });
  }
});

test("dist evidence reuses the bundle SBOM by default", async () => {
  const tempRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-release-dist-sbom-"));
  const evidenceDir = path.join(tempRoot, "release", "evidence");
  const distDir = path.join(tempRoot, "dist");
  const pythonBackendDir = path.join(tempRoot, "python_backend");
  const sbomPath = path.join(evidenceDir, "python-backend-cuda.cyclonedx.json");
  await fsp.mkdir(evidenceDir, { recursive: true });
  await fsp.mkdir(distDir, { recursive: true });
  await fsp.mkdir(pythonBackendDir, { recursive: true });
  await fsp.writeFile(
    sbomPath,
    JSON.stringify({
      bomFormat: "CycloneDX",
      specVersion: "1.5",
      metadata: {
        tools: { name: "uv", version: "0.11.28" },
        component: { name: "edmg-studio-backend", version: "1.2.0" },
      },
      components: [{ name: "torch" }],
      dependencies: [],
    }),
    "utf8",
  );
  const uvLockPath = path.join(pythonBackendDir, "uv.lock");
  await fsp.writeFile(uvLockPath, "locked dependencies", "utf8");
  const bundleManifest = await buildChecksumManifest({
    root: tempRoot,
    artifactPaths: [uvLockPath, sbomPath],
    metadata: {
      phase: "bundle",
      studioVersion: "1.2.0",
      acceleratorProfile: "cuda",
    },
  });
  await fsp.writeFile(
    path.join(evidenceDir, "bundle-artifacts.sha256.json"),
    `${JSON.stringify(bundleManifest, null, 2)}\n`,
    "utf8",
  );
  await fsp.writeFile(
    path.join(distDir, "EDMG-Studio-1.2.0-windows-x64-cuda-Setup.exe"),
    "installer",
    "utf8",
  );
  try {
    const before = await fsp.readFile(sbomPath, "utf8");
    const evidence = await writeReleaseEvidence({
      root: tempRoot,
      phase: "dist",
      profile: "cuda",
      artifactSet: "win-nsis",
      uvCommand: "must-not-run-for-dist-sbom-reuse",
      version: "1.2.0",
      env: {},
    });
    const after = await fsp.readFile(sbomPath, "utf8");

    assert.equal(after, before);
    assert.equal(evidence.sbom.reusedExisting, true);
    assert.ok(
      evidence.checksumManifest.artifacts.some((artifact) => artifact.path.endsWith("python-backend-cuda.cyclonedx.json")),
    );
  } finally {
    await fsp.rm(tempRoot, { recursive: true, force: true });
  }
});

test("dist SBOM reuse rejects stale bundle checksum evidence", async () => {
  const tempRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-release-stale-sbom-"));
  const evidenceDir = path.join(tempRoot, "release", "evidence");
  const pythonBackendDir = path.join(tempRoot, "python_backend");
  const sbomPath = path.join(evidenceDir, "python-backend-cuda.cyclonedx.json");
  const sbomContents = JSON.stringify({
    bomFormat: "CycloneDX",
    specVersion: "1.5",
    metadata: {
      tools: { name: "uv", version: "0.11.28" },
      component: { name: "edmg-studio-backend", version: "1.2.0" },
    },
    components: [],
    dependencies: [],
  });
  await fsp.mkdir(evidenceDir, { recursive: true });
  await fsp.mkdir(pythonBackendDir, { recursive: true });
  await fsp.writeFile(sbomPath, sbomContents, "utf8");
  const uvLockPath = path.join(pythonBackendDir, "uv.lock");
  await fsp.writeFile(uvLockPath, "locked dependencies", "utf8");
  const bundleManifest = await buildChecksumManifest({
    root: tempRoot,
    artifactPaths: [uvLockPath, sbomPath],
    metadata: { phase: "bundle", studioVersion: "1.2.0", acceleratorProfile: "cuda" },
  });
  await fsp.writeFile(
    path.join(evidenceDir, "bundle-artifacts.sha256.json"),
    `${JSON.stringify(bundleManifest, null, 2)}\n`,
    "utf8",
  );
  try {
    await assert.rejects(
      () => validateBundleEvidenceForSbomReuse({
        root: tempRoot,
        profile: "cuda",
        version: "9.9.9",
        sbomPath,
      }),
      /does not match the requested dist profile and version/,
    );

    await fsp.appendFile(sbomPath, "\n", "utf8");
    await assert.rejects(
      () => validateBundleEvidenceForSbomReuse({
        root: tempRoot,
        profile: "cuda",
        version: "1.2.0",
        sbomPath,
      }),
      /does not match current bytes/,
    );

    await fsp.writeFile(sbomPath, sbomContents, "utf8");
    await fsp.appendFile(uvLockPath, " drift", "utf8");
    await assert.rejects(
      () => validateBundleEvidenceForSbomReuse({
        root: tempRoot,
        profile: "cuda",
        version: "1.2.0",
        sbomPath,
      }),
      /python_backend\/uv\.lock/,
    );
  } finally {
    await fsp.rm(tempRoot, { recursive: true, force: true });
  }
});

test("code signing hook stays disabled without credentials", () => {
  const config = resolveCodeSigningConfig({});
  assert.equal(config.enabled, false);
  const plan = planCodeSigning(
    config,
    [path.join(studioRoot, "dist", "EDMG-Studio-1.1.0-windows-x64-directml-Setup.exe")],
    studioRoot,
  );
  assert.equal(plan.attempted, false);
  assert.match(plan.reason, /EDMG_CODE_SIGN_CERT/);
});

test("Windows Authenticode evidence summarizes the latest result for each artifact", () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "edmg-signature-evidence-"));
  const evidenceDir = path.join(tempRoot, "release", "evidence");
  fs.mkdirSync(evidenceDir, { recursive: true });
  fs.writeFileSync(
    path.join(evidenceDir, "windows-signatures.json"),
    JSON.stringify({
      schemaVersion: 1,
      runs: [
        {
          artifacts: [
            {
              path: "dist/EDMG Studio Setup.exe",
              action: "skipped",
              authenticodeStatus: "NotSigned",
              signToolVerified: false,
            },
          ],
        },
        {
          artifacts: [
            {
              path: "dist/EDMG Studio Setup.exe",
              action: "signed",
              authenticodeStatus: "Valid",
              signToolVerified: true,
            },
            {
              path: "dist/old-release.exe",
              action: "signed",
              authenticodeStatus: "Valid",
              signToolVerified: true,
            },
          ],
        },
      ],
    }),
  );
  try {
    const summary = readWindowsSignatureEvidence(tempRoot);
    assert.equal(summary.exists, true);
    assert.deepEqual(summary.valid, ["dist/EDMG Studio Setup.exe", "dist/old-release.exe"]);
    assert.deepEqual(summary.skipped, []);
    assert.deepEqual(summary.failed, []);

    const currentRelease = readWindowsSignatureEvidence(tempRoot, [
      path.join(tempRoot, "dist", "EDMG Studio Setup.exe"),
    ]);
    assert.deepEqual(currentRelease.valid, ["dist/EDMG Studio Setup.exe"]);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test("prepare-release-bundle and run-electron-builder integrate release evidence hooks", () => {
  const prepare = fs.readFileSync(path.join(__dirname, "prepare-release-bundle.mjs"), "utf8");
  const builder = fs.readFileSync(path.join(__dirname, "run-electron-builder.mjs"), "utf8");
  assert.match(prepare, /writeReleaseEvidence/);
  assert.match(builder, /writeReleaseEvidence/);
});
