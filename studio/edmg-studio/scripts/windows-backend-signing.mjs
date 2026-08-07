import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";

import {
  assertValidReleaseManifest,
  bundleMatchesManifest,
  collectBundleEntries,
} from "./release-python-toolchain.mjs";

function cloneJson(value) {
  return JSON.parse(JSON.stringify(value));
}

function requireFileEntry(entriesByPath, entryPath, label) {
  const entry = entriesByPath.get(entryPath);
  if (!entry || entry.type !== "file") {
    throw new Error(`${label} is missing from the staged backend inventory: ${entryPath}`);
  }
  return entry;
}

function entryFingerprint(entry) {
  return JSON.stringify(entry);
}

export function refreshWindowsBackendManifestForFinalBytes(
  manifest,
  actualEntries,
  {
    signingRequired = false,
    signingConfigured = false,
    finalizedAt = new Date().toISOString(),
  } = {},
) {
  assertValidReleaseManifest(manifest, { expectedPlatform: "win32" });
  if (!Array.isArray(actualEntries) || actualEntries.length === 0) {
    throw new Error("The final staged backend inventory is empty.");
  }
  if (signingRequired && !signingConfigured) {
    throw new Error("Required Windows signing cannot finalize an unsigned backend manifest.");
  }

  const previousEntries = manifest.bundleEntries;
  const previousByPath = new Map(previousEntries.map((entry) => [entry.path, entry]));
  const actualByPath = new Map(actualEntries.map((entry) => [entry.path, entry]));
  if (previousByPath.size !== previousEntries.length || actualByPath.size !== actualEntries.length) {
    throw new Error("Backend bundle inventories must not contain duplicate paths.");
  }

  const previousPaths = [...previousByPath.keys()].sort();
  const actualPaths = [...actualByPath.keys()].sort();
  if (JSON.stringify(previousPaths) !== JSON.stringify(actualPaths)) {
    throw new Error(
      "The staged backend file set changed after provenance generation; refusing to rebase the manifest.",
    );
  }

  const executablePaths = new Set([
    manifest.backendEntryPoint,
    manifest.hfBucketHelper.entryPoint,
  ]);
  const changedPaths = [];
  for (const entryPath of previousPaths) {
    const previous = previousByPath.get(entryPath);
    const actual = actualByPath.get(entryPath);
    if (entryFingerprint(previous) === entryFingerprint(actual)) continue;
    changedPaths.push(entryPath);
    if (!executablePaths.has(entryPath)) {
      throw new Error(
        `Non-signable backend bundle entry changed after provenance generation: ${entryPath}`,
      );
    }
  }
  if (!signingConfigured && changedPaths.length > 0) {
    throw new Error(
      `Unsigned QA packaging changed executable bytes unexpectedly: ${changedPaths.join(", ")}`,
    );
  }

  const launcher = requireFileEntry(actualByPath, manifest.backendEntryPoint, "Backend entry point");
  const helper = requireFileEntry(
    actualByPath,
    manifest.hfBucketHelper.entryPoint,
    "HF Bucket helper",
  );
  const files = actualEntries.filter((entry) => entry.type === "file");

  const finalized = cloneJson(manifest);
  finalized.bundleEntries = actualEntries;
  finalized.bundleEntryCount = actualEntries.length;
  finalized.bundleFileCount = files.length;
  finalized.bundleSize = files.reduce((total, entry) => total + entry.size, 0);
  finalized.binarySha256 = launcher.sha256;
  finalized.binarySize = launcher.size;
  finalized.hfBucketHelper.binarySha256 = helper.sha256;
  finalized.hfBucketHelper.binarySize = helper.size;
  finalized.windowsAuthenticode = {
    schemaVersion: 1,
    status: signingConfigured ? "verified" : "unsigned-local",
    required: Boolean(signingRequired),
    configured: Boolean(signingConfigured),
    manifestFinalizedAfterSigning: true,
    finalizedAt: String(finalizedAt),
    executablePaths: [...executablePaths].sort(),
    changedExecutablePaths: changedPaths.sort(),
  };

  assertValidReleaseManifest(finalized, { expectedPlatform: "win32" });
  return finalized;
}

export async function finalizeStagedWindowsBackendManifest({
  backendDirectory,
  manifestPath = path.join(backendDirectory, "backend-bundle-manifest.json"),
  signingRequired = false,
  signingConfigured = false,
  finalizedAt = new Date().toISOString(),
} = {}) {
  if (!backendDirectory || !path.isAbsolute(backendDirectory)) {
    throw new Error("A resolved staged Windows backend directory is required.");
  }
  if (!fs.existsSync(manifestPath) || !fs.statSync(manifestPath).isFile()) {
    throw new Error(`The staged backend manifest is missing: ${manifestPath}`);
  }

  let manifest;
  try {
    manifest = JSON.parse(await fsp.readFile(manifestPath, "utf8"));
  } catch (error) {
    throw new Error(`The staged backend manifest is not valid JSON: ${manifestPath}`, {
      cause: error,
    });
  }
  const actualEntries = await collectBundleEntries(backendDirectory);
  const finalized = refreshWindowsBackendManifestForFinalBytes(manifest, actualEntries, {
    signingRequired,
    signingConfigured,
    finalizedAt,
  });

  const temporaryPath = `${manifestPath}.finalizing-${process.pid}-${Date.now()}`;
  try {
    await fsp.writeFile(temporaryPath, `${JSON.stringify(finalized, null, 2)}\n`, "utf8");
    await fsp.rename(temporaryPath, manifestPath);
  } finally {
    await fsp.rm(temporaryPath, { force: true });
  }

  const written = JSON.parse(await fsp.readFile(manifestPath, "utf8"));
  assertValidReleaseManifest(written, { expectedPlatform: "win32" });
  if (!(await bundleMatchesManifest(backendDirectory, written))) {
    throw new Error("Final signed backend bytes do not match the refreshed release manifest.");
  }
  return written;
}
