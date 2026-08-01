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
  readWindowsSignatureEvidence,
  resolveCodeSigningConfig,
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
  const installer = path.join(distDir, "edmg-studio Setup 1.0.0.exe");
  const appImage = path.join(distDir, "edmg-studio-1.0.0.AppImage");
  const genericInnoInstaller = path.join(genericInnoDir, "EDMG-Studio-Setup-1.0.0.exe");
  const genericPayload = path.join(genericPayloadDir, "win-unpacked.7z");
  const innoInstaller = path.join(innoDir, "EDMG-Studio-Setup-1.0.0.exe");
  const payload = path.join(payloadDir, "win-unpacked.7z");
  fs.writeFileSync(installer, "installer");
  fs.writeFileSync(appImage, "appimage");
  fs.writeFileSync(genericInnoInstaller, "inno installer");
  fs.writeFileSync(genericPayload, "external payload");
  fs.writeFileSync(innoInstaller, "inno installer");
  fs.writeFileSync(payload, "external payload");
  try {
    assert.deepEqual(new Set(collectReleaseArtifactPaths(tempRoot, "dist", "win-nsis")), new Set([installer]));
    assert.deepEqual(new Set(collectReleaseArtifactPaths(tempRoot, "dist", "linux-appimage")), new Set([appImage]));
    assert.deepEqual(
      new Set(collectReleaseArtifactPaths(tempRoot, "dist", "win-inno")),
      new Set([genericInnoInstaller, genericPayload]),
    );
    assert.deepEqual(
      new Set(collectReleaseArtifactPaths(tempRoot, "dist", "win-inno-cuda")),
      new Set([innoInstaller, payload]),
    );
    assert.throws(() => collectReleaseArtifactPaths(tempRoot, "dist"), /artifact set is required/);
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

test("code signing hook stays disabled without credentials", () => {
  const config = resolveCodeSigningConfig({});
  assert.equal(config.enabled, false);
  const plan = planCodeSigning(config, [path.join(studioRoot, "dist", "EDMG Studio Setup 1.1.0.exe")], studioRoot);
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
