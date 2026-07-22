import assert from "node:assert/strict";
import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  assertValidReleaseManifest,
  bundleMatchesManifest,
  sha256File,
} from "./release-python-toolchain.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const repoRoot = path.resolve(root, "..", "..");
const backendBinaryName = process.platform === "win32" ? "edmg-studio-backend.exe" : "edmg-studio-backend";
const lockPath = path.join(root, "python_backend", "uv.lock");

async function validateBundle(directory, expected = null) {
  const manifestPath = path.join(directory, "backend-bundle-manifest.json");
  const binaryPath = path.join(directory, backendBinaryName);
  assert.ok(fs.existsSync(manifestPath), `Backend release manifest is missing: ${manifestPath}`);
  assert.ok(fs.existsSync(binaryPath), `Backend release binary is missing: ${binaryPath}`);
  const manifest = JSON.parse(await fsp.readFile(manifestPath, "utf8"));
  assertValidReleaseManifest(manifest);
  assert.equal(
    await bundleMatchesManifest(directory, manifest),
    true,
    `Backend onedir contents do not match ${manifestPath}`,
  );
  const stat = await fsp.stat(binaryPath);
  assert.equal(stat.size, manifest.binarySize, `Backend binary size does not match ${manifestPath}`);
  assert.equal(await sha256File(binaryPath), manifest.binarySha256, `Backend binary hash does not match ${manifestPath}`);
  assert.equal(await sha256File(lockPath), manifest.lockSha256, `uv.lock hash does not match ${manifestPath}`);

  for (const input of manifest.fingerprintInputs) {
    const sourcePath = path.resolve(repoRoot, input.path);
    const relative = path.relative(repoRoot, sourcePath);
    assert.ok(relative && relative !== ".." && !relative.startsWith(`..${path.sep}`), `Unsafe fingerprint path: ${input.path}`);
    assert.ok(fs.existsSync(sourcePath), `Release fingerprint input is missing: ${input.path}`);
    assert.equal(await sha256File(sourcePath), input.sha256, `Release fingerprint input changed after packaging: ${input.path}`);
  }
  if (expected) {
    assert.deepEqual(
      manifest,
      expected,
      "Staged backend manifest differs from the prepared release provenance",
    );
  }
  return manifest;
}

async function main() {
  const preparedDir = path.join(root, "electron-resources", "backend");
  const prepared = await validateBundle(preparedDir);
  const stagedDir = path.join(root, "release", "staged-app", "electron-resources", "backend");
  if (fs.existsSync(stagedDir)) await validateBundle(stagedDir, prepared);
  console.log(
    `[backend-release-manifest] ${prepared.acceleratorProfile} backend verified: ` +
      `${prepared.pythonVersion}, uv ${prepared.uvVersion}, lock ${prepared.lockSha256}`,
  );
}

main().catch((error) => {
  console.error("[backend-release-manifest] FAILED", error);
  process.exit(1);
});
