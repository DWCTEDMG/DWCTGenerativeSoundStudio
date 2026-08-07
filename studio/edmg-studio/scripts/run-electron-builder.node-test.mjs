import assert from "node:assert/strict";
import fs from "node:fs";
import fsp from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  PINNED_UV_VERSION,
  RELEASE_CAPABILITY_EXTRAS,
  bundleMatchesManifest,
  collectBundleEntries,
} from "./release-python-toolchain.mjs";
import {
  requireStagedBackendPlatform,
  resolveRequestedInstallerTarget,
  withLinuxProfileArtifactName,
} from "./run-electron-builder.mjs";
import { finalizeWindowsPackagedBackend } from "./electron-builder-after-pack.mjs";
import { finalizeStagedWindowsBackendManifest } from "./windows-backend-signing.mjs";

test("recognizes the Electron Builder Windows aliases used by release scripts", () => {
  for (const flag of ["-w", "--win", "--windows", "--win=nsis"]) {
    assert.deepEqual(resolveRequestedInstallerTarget([flag, "--x64"], "win32"), {
      platform: "win32",
      artifactSet: "win-nsis",
      signingArgs: ["--win"],
    });
  }
});

test("recognizes the Electron Builder Linux aliases used by release scripts", () => {
  for (const flag of ["-l", "--linux", "--linux=AppImage"]) {
    assert.deepEqual(resolveRequestedInstallerTarget([flag, "AppImage", "--x64"], "linux"), {
      platform: "linux",
      artifactSet: "linux-appimage",
      signingArgs: ["--linux"],
    });
  }
});

test("rejects combined installer targets before considering the host", () => {
  assert.throws(
    () => resolveRequestedInstallerTarget(["--linux", "-w"], "darwin"),
    /Windows or Linux, not both/,
  );
});

test("rejects release targets that do not match the build host", () => {
  assert.throws(
    () => resolveRequestedInstallerTarget(["--win"], "linux"),
    /Windows Electron installers must be built on Windows/,
  );
  assert.throws(
    () => resolveRequestedInstallerTarget(["--linux"], "win32"),
    /Linux Electron installers must be built on Linux/,
  );
  assert.throws(
    () => resolveRequestedInstallerTarget(["-l"], "darwin"),
    /Linux Electron installers must be built on Linux/,
  );
});

test("does not mistake unrelated flags or values for platform targets", () => {
  const unrelatedArgs = [
    "--dir",
    "--x64",
    "--window-size=1200x800",
    "--windows-signing=false",
    "--linux-notes=README.md",
    "-lint",
    "-watch",
    "-c.directories.app=release/staged-app",
    "C:\\release\\win-output",
  ];
  assert.equal(resolveRequestedInstallerTarget(unrelatedArgs, "win32"), null);
  assert.equal(resolveRequestedInstallerTarget(unrelatedArgs, "linux"), null);
});

function createManifestFixture(t, manifest) {
  const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), "edmg-builder-guard-"));
  t.after(() => fs.rmSync(rootDir, { recursive: true, force: true }));
  const manifestPath = path.join(
    rootDir,
    "release",
    "staged-app",
    "electron-resources",
    "backend",
    "backend-bundle-manifest.json",
  );
  fs.mkdirSync(path.dirname(manifestPath), { recursive: true });
  fs.writeFileSync(manifestPath, JSON.stringify(manifest), "utf8");
  return { rootDir, manifestPath };
}

test("accepts a staged backend manifest matching the requested target", (t) => {
  const { rootDir } = createManifestFixture(t, { platform: "linux", acceleratorProfile: "cuda" });
  assert.deepEqual(requireStagedBackendPlatform({ targetPlatform: "linux", rootDir }), {
    platform: "linux",
    acceleratorProfile: "cuda",
  });
});

test("requires a readable staged backend manifest for an installer target", (t) => {
  const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), "edmg-builder-guard-missing-"));
  t.after(() => fs.rmSync(rootDir, { recursive: true, force: true }));
  assert.throws(
    () => requireStagedBackendPlatform({ targetPlatform: "win32", rootDir }),
    /staged backend manifest is required/,
  );
});

test("rejects malformed, incomplete, and cross-platform staged manifests", (t) => {
  const malformed = createManifestFixture(t, { platform: "linux" });
  fs.writeFileSync(malformed.manifestPath, "{", "utf8");
  assert.throws(
    () => requireStagedBackendPlatform({ targetPlatform: "linux", rootDir: malformed.rootDir }),
    /not valid JSON/,
  );

  const incomplete = createManifestFixture(t, { acceleratorProfile: "cuda" });
  assert.throws(
    () => requireStagedBackendPlatform({ targetPlatform: "linux", rootDir: incomplete.rootDir }),
    /does not declare a platform/,
  );

  const mismatched = createManifestFixture(t, { platform: "win32", acceleratorProfile: "cuda" });
  assert.throws(
    () => requireStagedBackendPlatform({ targetPlatform: "linux", rootDir: mismatched.rootDir }),
    /target linux cannot package backend win32/,
  );
});

test("adds a literal profile-specific Linux AppImage artifact name", () => {
  assert.deepEqual(
    withLinuxProfileArtifactName(["-l", "AppImage"], {
      targetPlatform: "linux",
      acceleratorProfile: "CUDA",
    }),
    ["-l", "AppImage", "-c.artifactName=EDMG-Studio-${version}-linux-x64-cuda.${ext}"],
  );
});

test("preserves a caller-provided artifact name and ignores artifactName false positives", () => {
  assert.deepEqual(
    withLinuxProfileArtifactName(["--linux", "-c.artifactName=custom-${version}.${ext}"], {
      targetPlatform: "linux",
      acceleratorProfile: "cpu",
    }),
    ["--linux", "-c.artifactName=custom-${version}.${ext}"],
  );
  assert.deepEqual(
    withLinuxProfileArtifactName(["--linux", "-c.artifactNameSuffix=debug"], {
      targetPlatform: "linux",
      acceleratorProfile: "cpu",
    }),
    ["--linux", "-c.artifactNameSuffix=debug", "-c.artifactName=EDMG-Studio-${version}-linux-x64-cpu.${ext}"],
  );
});

test("requires a filename-safe Linux profile and leaves non-Linux arguments unchanged", () => {
  assert.throws(
    () =>
      withLinuxProfileArtifactName(["--linux"], {
        targetPlatform: "linux",
        acceleratorProfile: "cuda/../../other",
      }),
    /filename-safe acceleratorProfile/,
  );
  assert.deepEqual(
    withLinuxProfileArtifactName(["--win"], {
      targetPlatform: "win32",
      acceleratorProfile: "cuda/../../other",
    }),
    ["--win"],
  );
});

async function createBackendSigningFixture(t) {
  const backendDirectory = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-signed-manifest-"));
  t.after(() => fsp.rm(backendDirectory, { recursive: true, force: true }));

  const backendEntryPoint = "edmg-studio-backend.exe";
  const helperEntryPoint = "edmg-hf-bucket-helper.exe";
  const hfRuntimeBundleEvidence = {
    huggingfaceHubMetadata: "_internal/huggingface_hub-0.36.2.dist-info/METADATA",
    hfTransferMetadata: "_internal/hf_transfer-0.1.9.dist-info/METADATA",
    hfTransferModule: "_internal/hf_transfer/hf_transfer.pyd",
    hfXetMetadata: "_internal/hf_xet-1.5.1.dist-info/METADATA",
    hfXetModule: "_internal/hf_xet/hf_xet.pyd",
  };
  const fileContents = new Map([
    [backendEntryPoint, "unsigned backend bytes"],
    [helperEntryPoint, "unsigned helper bytes"],
    ["launcher_env.defaults.json", "{}\n"],
    ...Object.values(hfRuntimeBundleEvidence).map((entryPath) => [entryPath, `fixture:${entryPath}`]),
  ]);
  for (const [relativePath, contents] of fileContents) {
    const filePath = path.join(backendDirectory, ...relativePath.split("/"));
    await fsp.mkdir(path.dirname(filePath), { recursive: true });
    await fsp.writeFile(filePath, contents, "utf8");
  }

  const bundleEntries = await collectBundleEntries(backendDirectory);
  const entry = (entryPath) => bundleEntries.find((candidate) => candidate.path === entryPath);
  const launcher = entry(backendEntryPoint);
  const helper = entry(helperEntryPoint);
  const defaults = entry("launcher_env.defaults.json");
  const cpuIndex = "https://download.pytorch.org/whl/cpu";
  const manifest = {
    schemaVersion: 5,
    ok: true,
    builder: "scripts/prepare-release-bundle.mjs",
    platform: "win32",
    sourceHash: "1".repeat(64),
    sourceFileCount: 10,
    fingerprintInputs: [
      { path: ".python-version", sha256: "4".repeat(64) },
      { path: "studio/edmg-studio/python_backend/pyproject.toml", sha256: "5".repeat(64) },
      { path: "studio/edmg-studio/python_backend/uv.lock", sha256: "2".repeat(64) },
      { path: "studio/edmg-studio/python_backend/hf_bucket_helper/pyproject.toml", sha256: "7".repeat(64) },
      { path: "studio/edmg-studio/python_backend/hf_bucket_helper/uv.lock", sha256: "8".repeat(64) },
      { path: "studio/edmg-studio/launcher_env.defaults.json", sha256: defaults.sha256 },
    ],
    lockSha256: "2".repeat(64),
    acceleratorProfile: "cpu",
    capabilityExtras: [...RELEASE_CAPABILITY_EXTRAS],
    pythonVersion: "3.12.10",
    pythonImplementation: "CPython",
    uvVersion: PINNED_UV_VERSION,
    pyinstallerVersion: "6.21.0",
    torchIndex: cpuIndex,
    torchPackages: [
      { name: "torch", version: "2.8.0+cpu", index: cpuIndex },
      { name: "torchaudio", version: "2.8.0+cpu", index: cpuIndex },
      { name: "torchvision", version: "0.23.0+cpu", index: cpuIndex },
    ],
    hfRuntimePackages: [
      { name: "huggingface-hub", version: "0.36.2" },
      { name: "hf-transfer", version: "0.1.9" },
      { name: "hf-xet", version: "1.5.1" },
    ],
    hfRuntimeBundleEvidence,
    nltkResources: [{
      name: "punkt",
      url: "https://raw.githubusercontent.com/nltk/nltk_data/immutable/punkt.zip",
      sha256: "6".repeat(64),
      size: 1,
    }],
    bundleLayout: "onedir",
    backendEntryPoint,
    bundleEntries,
    bundleEntryCount: bundleEntries.length,
    bundleFileCount: bundleEntries.length,
    bundleSize: bundleEntries.reduce((total, candidate) => total + candidate.size, 0),
    binarySha256: launcher.sha256,
    binarySize: launcher.size,
    hfBucketHelper: {
      entryPoint: helperEntryPoint,
      helperVersion: "1.0.0",
      huggingfaceHubVersion: "1.20.1",
      hfXetVersion: "1.5.1",
      lockSha256: "8".repeat(64),
      binarySha256: helper.sha256,
      binarySize: helper.size,
    },
    launcherEnvDefaults: {
      entryPoint: "launcher_env.defaults.json",
      sha256: defaults.sha256,
      size: defaults.size,
    },
    reusedExistingBuild: false,
    preparedAt: "2026-08-06T00:00:00.000Z",
  };
  const manifestPath = path.join(backendDirectory, "backend-bundle-manifest.json");
  await fsp.writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  return {
    backendDirectory,
    backendPath: path.join(backendDirectory, backendEntryPoint),
    helperPath: path.join(backendDirectory, helperEntryPoint),
    defaultsPath: path.join(backendDirectory, "launcher_env.defaults.json"),
    manifest,
    manifestPath,
  };
}

test("finalizes signed backend and helper bytes from their final packaged inventory", async (t) => {
  const fixture = await createBackendSigningFixture(t);
  await fsp.appendFile(fixture.backendPath, "::authenticode", "utf8");
  await fsp.appendFile(fixture.helperPath, "::authenticode", "utf8");

  const finalized = await finalizeStagedWindowsBackendManifest({
    backendDirectory: fixture.backendDirectory,
    signingRequired: true,
    signingConfigured: true,
    finalizedAt: "2026-08-06T12:00:00.000Z",
  });

  assert.equal(finalized.windowsAuthenticode.status, "verified");
  assert.equal(finalized.windowsAuthenticode.required, true);
  assert.deepEqual(finalized.windowsAuthenticode.changedExecutablePaths, [
    "edmg-hf-bucket-helper.exe",
    "edmg-studio-backend.exe",
  ]);
  assert.notEqual(finalized.binarySha256, fixture.manifest.binarySha256);
  assert.notEqual(finalized.hfBucketHelper.binarySha256, fixture.manifest.hfBucketHelper.binarySha256);
  assert.equal(await bundleMatchesManifest(fixture.backendDirectory, finalized), true);
  assert.deepEqual(
    JSON.parse(await fsp.readFile(fixture.manifestPath, "utf8")),
    finalized,
  );
});

test("Electron Builder afterPack finalizes the copied unsigned QA backend manifest", async (t) => {
  const appOutDir = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-after-pack-"));
  t.after(() => fsp.rm(appOutDir, { recursive: true, force: true }));
  const fixture = await createBackendSigningFixture(t);
  const packagedBackend = path.join(appOutDir, "resources", "backend");
  await fsp.mkdir(path.dirname(packagedBackend), { recursive: true });
  await fsp.cp(fixture.backendDirectory, packagedBackend, { recursive: true });

  const finalized = await finalizeWindowsPackagedBackend(
    { electronPlatformName: "win32", appOutDir },
    {
      env: {
        EDMG_WINDOWS_SIGNING_REQUIRED: "0",
        EDMG_WINDOWS_SIGNING_CONFIGURED: "0",
      },
      finalizedAt: "2026-08-06T13:00:00.000Z",
    },
  );

  assert.equal(finalized.windowsAuthenticode.status, "unsigned-local");
  assert.equal(finalized.windowsAuthenticode.manifestFinalizedAfterSigning, true);
  assert.equal(await bundleMatchesManifest(packagedBackend, finalized), true);
  assert.equal(
    JSON.parse(await fsp.readFile(path.join(packagedBackend, "backend-bundle-manifest.json"), "utf8"))
      .windowsAuthenticode.status,
    "unsigned-local",
  );
});

test("refuses to hide non-executable or unsigned byte drift in a refreshed manifest", async (t) => {
  const nonExecutable = await createBackendSigningFixture(t);
  await fsp.appendFile(nonExecutable.defaultsPath, "tampered", "utf8");
  await assert.rejects(
    finalizeStagedWindowsBackendManifest({
      backendDirectory: nonExecutable.backendDirectory,
      signingConfigured: true,
    }),
    /Non-signable backend bundle entry changed/,
  );

  const unsigned = await createBackendSigningFixture(t);
  await fsp.appendFile(unsigned.backendPath, "unexpected", "utf8");
  await assert.rejects(
    finalizeStagedWindowsBackendManifest({
      backendDirectory: unsigned.backendDirectory,
      signingConfigured: false,
    }),
    /Unsigned QA packaging changed executable bytes unexpectedly/,
  );
});

test("Inno packaging signs setup and uninstaller and always regenerates a bound payload", () => {
  const studioRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const scriptPath = path.join(studioRoot, "packaging", "windows", "build_inno_external.ps1");
  const source = fs.readFileSync(scriptPath, "utf8");

  assert.doesNotMatch(source, /ReusePayloadArchive/);
  assert.match(source, /Remove-DirectoryIfExists \$PayloadRoot/);
  assert.match(source, /SignTool=edmgstudio/);
  assert.match(source, /SignedUninstaller=yes/);
  assert.match(source, /\/Sedmgstudio=/);
  assert.match(source, /-ArtifactPaths \$f -RequireSigning/);
  assert.match(source, /payload-integrity\.json/);
  assert.match(source, /backendManifestSha256/);
  assert.match(source, /pre-archive payload"[\s\S]{0,120}-VerifyOnly/);
  assert.match(source, /Get-ChildItem -LiteralPath \$WinUnpackedDir -Force/);
  assert.match(source, /Where-Object \{ \$_.Name -notlike "unins\*" \}/);
  assert.doesNotMatch(source, /Name: "\{app\}\\\*"/);
  assert.doesNotMatch(source, /Name: "\{app\}\\resources\\backend"/);
});
