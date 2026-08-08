import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { createHash } from "node:crypto";

import { buildIdentity } from "./build-identity.mjs";

test("build identity uses Electron version metadata and the packaged backend manifest", () => {
  const resourcesPath = fs.mkdtempSync(path.join(os.tmpdir(), "edmg-build-identity-"));
  try {
    const backendDir = path.join(resourcesPath, "backend");
    const backendContent = Buffer.from("verified packaged backend\n", "utf8");
    const backendEntryPoint = "edmg-studio-backend.exe";
    fs.mkdirSync(backendDir, { recursive: true });
    fs.writeFileSync(path.join(backendDir, backendEntryPoint), backendContent);
    fs.writeFileSync(path.join(backendDir, "backend-bundle-manifest.json"), JSON.stringify({
      schemaVersion: 5,
      ok: true,
      builder: "scripts/prepare-release-bundle.mjs",
      platform: "win32",
      sourceHash: "A".repeat(64),
      sourceFileCount: 267,
      lockSha256: "B".repeat(64),
      acceleratorProfile: "cuda",
      pythonVersion: "3.12.10",
      backendEntryPoint,
      binarySize: backendContent.length,
      binarySha256: createHash("sha256").update(backendContent).digest("hex"),
    }));

    const identity = buildIdentity({
      app: {
        getVersion: () => "1.2.0",
        getPath: (name) => name === "exe" ? "E:\\EDMG Studio\\EDMG Studio.exe" : "",
        isPackaged: true,
      },
      resourcesPath,
      platform: "win32",
      arch: "x64",
      electronVersion: "39.2.7",
    });

    assert.deepEqual(identity.desktop, {
      version: "1.2.0",
      packaged: true,
      platform: "win32",
      arch: "x64",
      electronVersion: "39.2.7",
      executablePath: "E:\\EDMG Studio\\EDMG Studio.exe",
    });
    assert.equal(identity.backendBundle.available, true);
    assert.equal(identity.backendBundle.binaryVerified, true);
    assert.equal(identity.backendBundle.acceleratorProfile, "cuda");
    assert.equal(identity.backendBundle.sourceHash, "a".repeat(64));
    assert.equal(identity.backendBundle.lockSha256, "b".repeat(64));
    assert.equal(
      identity.backendBundle.binarySha256,
      createHash("sha256").update(backendContent).digest("hex"),
    );
  } finally {
    fs.rmSync(resourcesPath, { recursive: true, force: true });
  }
});

test("build identity fails closed when provenance is missing or malformed", () => {
  const identity = buildIdentity({
    app: { getVersion: () => "1.2.0-dev", isPackaged: false },
    resourcesPath: "Z:\\missing-resources",
    rootDir: "Z:\\missing-source",
    platform: "win32",
    arch: "x64",
    electronVersion: "39.2.7",
  });

  assert.equal(identity.ok, true);
  assert.equal(identity.desktop.version, "1.2.0-dev");
  assert.equal(identity.desktop.packaged, false);
  assert.equal(identity.desktop.executablePath, "");
  assert.deepEqual(identity.backendBundle, {
    available: false,
    binaryVerified: false,
    schemaVersion: null,
    builder: "",
    platform: "",
    backendEntryPoint: "",
    acceleratorProfile: "",
    pythonVersion: "",
    sourceHash: "",
    sourceFileCount: null,
    lockSha256: "",
    binarySha256: "",
  });
});

test("build identity fails closed when Electron cannot resolve the executable path", () => {
  const identity = buildIdentity({
    app: {
      getVersion: () => "1.2.0",
      getPath: () => {
        throw new Error("app path unavailable");
      },
      isPackaged: true,
    },
    resourcesPath: "Z:\\missing-resources",
    platform: "win32",
  });

  assert.equal(identity.ok, true);
  assert.equal(identity.desktop.executablePath, "");
});

test("packaged build identity does not expose malformed manifest digests", () => {
  const resourcesPath = fs.mkdtempSync(path.join(os.tmpdir(), "edmg-build-identity-invalid-"));
  try {
    const backendDir = path.join(resourcesPath, "backend");
    fs.mkdirSync(backendDir, { recursive: true });
    fs.writeFileSync(path.join(backendDir, "backend-bundle-manifest.json"), JSON.stringify({
      schemaVersion: 5,
      ok: true,
      sourceHash: "not-a-digest",
      lockSha256: "also-invalid",
      binarySha256: "c".repeat(64),
    }));

    const identity = buildIdentity({
      app: { getVersion: () => "1.2.0", isPackaged: true },
      resourcesPath,
      platform: "win32",
      arch: "x64",
      electronVersion: "41.10.3",
    });

    assert.equal(identity.backendBundle.available, false);
    assert.equal(identity.backendBundle.sourceHash, "");
    assert.equal(identity.backendBundle.lockSha256, "");
    assert.equal(identity.backendBundle.binarySha256, "c".repeat(64));
  } finally {
    fs.rmSync(resourcesPath, { recursive: true, force: true });
  }
});

test("packaged build identity rejects a non-positive manifest schema", () => {
  const resourcesPath = fs.mkdtempSync(path.join(os.tmpdir(), "edmg-build-identity-schema-"));
  try {
    const backendDir = path.join(resourcesPath, "backend");
    fs.mkdirSync(backendDir, { recursive: true });
    fs.writeFileSync(path.join(backendDir, "backend-bundle-manifest.json"), JSON.stringify({
      schemaVersion: 0,
      ok: true,
      sourceHash: "a".repeat(64),
      lockSha256: "b".repeat(64),
      binarySha256: "c".repeat(64),
    }));

    const identity = buildIdentity({
      app: { getVersion: () => "1.2.0", isPackaged: true },
      resourcesPath,
      platform: "win32",
      arch: "x64",
      electronVersion: "41.10.3",
    });

    assert.equal(identity.backendBundle.available, false);
    assert.equal(identity.backendBundle.schemaVersion, null);
  } finally {
    fs.rmSync(resourcesPath, { recursive: true, force: true });
  }
});

test("packaged build identity rejects platform drift and modified installed backend bytes", () => {
  const resourcesPath = fs.mkdtempSync(path.join(os.tmpdir(), "edmg-build-identity-tamper-"));
  try {
    const backendDir = path.join(resourcesPath, "backend");
    const backendPath = path.join(backendDir, "edmg-studio-backend.exe");
    const original = Buffer.from("original backend\n", "utf8");
    fs.mkdirSync(backendDir, { recursive: true });
    fs.writeFileSync(backendPath, original);
    const manifestPath = path.join(backendDir, "backend-bundle-manifest.json");
    const manifest = {
      schemaVersion: 5,
      ok: true,
      platform: "linux",
      backendEntryPoint: "edmg-studio-backend.exe",
      binarySize: original.length,
      sourceHash: "a".repeat(64),
      lockSha256: "b".repeat(64),
      binarySha256: createHash("sha256").update(original).digest("hex"),
    };
    fs.writeFileSync(manifestPath, JSON.stringify(manifest));

    const app = { getVersion: () => "1.2.0", isPackaged: true };
    assert.equal(buildIdentity({ app, resourcesPath, platform: "win32" }).backendBundle.available, false);

    manifest.platform = "win32";
    fs.writeFileSync(manifestPath, JSON.stringify(manifest));
    fs.writeFileSync(backendPath, "modified backend\n", "utf8");
    const modified = buildIdentity({ app, resourcesPath, platform: "win32" });
    assert.equal(modified.backendBundle.available, false);
    assert.equal(modified.backendBundle.binaryVerified, false);
  } finally {
    fs.rmSync(resourcesPath, { recursive: true, force: true });
  }
});
