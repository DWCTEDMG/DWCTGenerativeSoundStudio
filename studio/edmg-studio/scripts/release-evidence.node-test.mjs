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

test("release artifact inventory includes bundle manifests and dist installers", () => {
  const bundlePaths = collectReleaseArtifactPaths(studioRoot, "bundle");
  assert.ok(
    bundlePaths.some((filePath) => filePath.replaceAll("\\", "/").endsWith("python_backend/uv.lock")),
    "bundle inventory should include uv.lock when present",
  );

  const tempRoot = path.join(os.tmpdir(), `edmg-release-evidence-${process.pid}`);
  const distDir = path.join(tempRoot, "dist");
  fs.mkdirSync(distDir, { recursive: true });
  const installer = path.join(distDir, "edmg-studio Setup 1.0.0.exe");
  fs.writeFileSync(installer, "installer");
  try {
    const distPaths = collectReleaseArtifactPaths(tempRoot, "dist");
    assert.deepEqual(distPaths, [installer]);
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

test("prepare-release-bundle and run-electron-builder integrate release evidence hooks", () => {
  const prepare = fs.readFileSync(path.join(__dirname, "prepare-release-bundle.mjs"), "utf8");
  const builder = fs.readFileSync(path.join(__dirname, "run-electron-builder.mjs"), "utf8");
  assert.match(prepare, /writeReleaseEvidence/);
  assert.match(builder, /writeReleaseEvidence/);
});
