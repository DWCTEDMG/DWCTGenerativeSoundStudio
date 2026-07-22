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
  assertNoDynamicDependencyOverrides,
  assertPinnedUvVersion,
  assertPython312,
  assertTorchIndexForProfile,
  assertTrackedCleanDependencyStatus,
  binaryMatchesManifest,
  bundleMatchesManifest,
  collectBundleEntries,
  releaseUvEnvironment,
  releaseProvenanceMatches,
  resolveAcceleratorProfile,
  selectedExtras,
  sha256File,
  uvLockCheckArgs,
  uvRunArgs,
  uvSyncArgs,
  uvExportCycloneDxArgs,
  validateReleaseManifest,
} from "./release-python-toolchain.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const studioRoot = path.resolve(__dirname, "..");

function validManifest(overrides = {}) {
  const cpuIndex = "https://download.pytorch.org/whl/cpu";
  const backendEntryPoint = process.platform === "win32" ? "edmg-studio-backend.exe" : "edmg-studio-backend";
  const binarySha256 = "3".repeat(64);
  const binarySize = 123;
  return {
    schemaVersion: 3,
    ok: true,
    sourceHash: "1".repeat(64),
    sourceFileCount: 10,
    lockSha256: "2".repeat(64),
    binarySha256,
    binarySize,
    bundleLayout: "onedir",
    backendEntryPoint,
    bundleEntries: [
      { path: backendEntryPoint, type: "file", size: binarySize, sha256: binarySha256 },
    ],
    bundleEntryCount: 1,
    bundleFileCount: 1,
    bundleSize: binarySize,
    acceleratorProfile: "cpu",
    capabilityExtras: [...RELEASE_CAPABILITY_EXTRAS],
    uvVersion: PINNED_UV_VERSION,
    pythonVersion: "3.12.10",
    pythonImplementation: "CPython",
    pyinstallerVersion: "6.16.0",
    torchIndex: cpuIndex,
    torchPackages: [
      { name: "torch", version: "2.8.0+cpu", index: cpuIndex },
      { name: "torchaudio", version: "2.8.0+cpu", index: cpuIndex },
      { name: "torchvision", version: "0.23.0+cpu", index: cpuIndex },
    ],
    fingerprintInputs: [
      { path: ".python-version", sha256: "4".repeat(64) },
      { path: "studio/edmg-studio/python_backend/pyproject.toml", sha256: "5".repeat(64) },
      { path: "studio/edmg-studio/python_backend/uv.lock", sha256: "2".repeat(64) },
    ],
    nltkResources: [
      {
        name: "punkt",
        url: "https://raw.githubusercontent.com/nltk/nltk_data/immutable/packages/tokenizers/punkt.zip",
        sha256: "6".repeat(64),
        size: 1,
      },
    ],
    ...overrides,
  };
}

test("accelerator profile selection is strict and platform aware", () => {
  assert.equal(resolveAcceleratorProfile({ argv: ["--profile", "cpu"], env: {}, platform: "win32" }), "cpu");
  assert.equal(resolveAcceleratorProfile({ argv: [], env: {}, platform: "win32" }), "directml");
  assert.equal(resolveAcceleratorProfile({ argv: [], env: {}, platform: "linux" }), "cpu");
  assert.equal(
    resolveAcceleratorProfile({ argv: [], env: { EDMG_BACKEND_ACCELERATOR_PROFILE: "cuda" }, platform: "linux" }),
    "cuda",
  );
  assert.throws(
    () => resolveAcceleratorProfile({ argv: ["--profile", "cpu"], env: { EDMG_BACKEND_ACCELERATOR_PROFILE: "cuda" } }),
    /Conflicting accelerator profiles/,
  );
  assert.throws(() => resolveAcceleratorProfile({ argv: ["--profile", "CPU"], env: {} }), /Invalid accelerator profile/);
  assert.throws(() => resolveAcceleratorProfile({ argv: ["--profile", "directml"], env: {}, platform: "linux" }), /only on Windows/);
  assert.throws(() => resolveAcceleratorProfile({ argv: ["--extra", "cpu"], env: {} }), /Unknown/);
});

test("dynamic dependency and index overrides are rejected", () => {
  assert.doesNotThrow(() => assertNoDynamicDependencyOverrides({}));
  for (const name of [
    "EDMG_BACKEND_BUNDLE_EXTRA",
    "EDMG_BACKEND_TORCH_INDEX_URL",
    "PIP_INDEX_URL",
    "UV_INDEX",
    "UV_CONFIG_FILE",
    "UV_PROJECT_ENVIRONMENT",
  ]) {
    assert.throws(() => assertNoDynamicDependencyOverrides({ [name]: "unexpected" }), new RegExp(name));
  }
});

test("frozen uv commands compose one accelerator with deterministic capabilities", () => {
  assert.deepEqual(selectedExtras("cpu"), ["cpu", ...RELEASE_CAPABILITY_EXTRAS]);
  assert.deepEqual(uvLockCheckArgs(), ["lock", "--check"]);
  assert.deepEqual(uvExportCycloneDxArgs("cpu").slice(0, 4), ["export", "--format", "cyclonedx1.5", "--frozen"]);
  assert.deepEqual(uvSyncArgs("cuda"), [
    "sync",
    "--frozen",
    "--no-default-groups",
    "--extra",
    "cuda",
    "--extra",
    "core",
    "--extra",
    "audio",
    "--extra",
    "asr",
    "--extra",
    "internal-video",
    "--extra",
    "aws",
    "--group",
    "build",
  ]);
  const run = uvRunArgs("cpu", ["pyinstaller", "pyinstaller.spec", "--clean", "--noconfirm"]);
  assert.deepEqual(run.slice(0, 4), ["run", "--frozen", "--no-sync", "--no-default-groups"]);
  assert.deepEqual(run.slice(-6), ["--group", "build", "pyinstaller", "pyinstaller.spec", "--clean", "--noconfirm"]);
  assert.equal(run.filter((value) => value === "--extra").length, 6);
});

test("release builds isolate accelerator environments from the source runtime", () => {
  const sourceEnv = { KEEP_ME: "yes", UV_LINK_MODE: "hardlink" };
  const releaseEnv = releaseUvEnvironment(studioRoot, "cuda", sourceEnv);
  assert.equal(releaseEnv.KEEP_ME, "yes");
  assert.equal(releaseEnv.UV_LINK_MODE, "copy");
  assert.equal(
    releaseEnv.UV_PROJECT_ENVIRONMENT,
    path.join(studioRoot, "release", "uv-environments", "cuda"),
  );
  assert.equal(sourceEnv.UV_PROJECT_ENVIRONMENT, undefined);
  assert.throws(() => releaseUvEnvironment(studioRoot, "unknown", {}), /Unsupported accelerator profile/);
});

test("uv, Python, and Torch provenance checks enforce the release pins", () => {
  assert.equal(assertPinnedUvVersion("uv 0.11.28 (build metadata)"), "0.11.28");
  assert.throws(() => assertPinnedUvVersion("uv 0.11.27"), /pinned uv 0\.11\.28/);
  assert.equal(assertPython312("3.12.10"), "3.12.10");
  assert.throws(() => assertPython312("3.13.1"), /Python 3\.12/);
  assert.equal(assertTorchIndexForProfile("directml", "https://download.pytorch.org/whl/cpu/"), "https://download.pytorch.org/whl/cpu");
  assert.equal(assertTorchIndexForProfile("cuda", "https://download.pytorch.org/whl/cu130"), "https://download.pytorch.org/whl/cu130");
  assert.throws(() => assertTorchIndexForProfile("cuda", "https://example.invalid/cu130"), /fixed locked/);
});

test("release dependency metadata must be tracked and clean", () => {
  assert.doesNotThrow(() => assertTrackedCleanDependencyStatus({ trackedStatus: 0, dirtyStatus: "", paths: ["uv.lock"] }));
  assert.throws(
    () => assertTrackedCleanDependencyStatus({ trackedStatus: 1, dirtyStatus: "", paths: ["uv.lock"] }),
    /tracked by git/,
  );
  assert.throws(
    () => assertTrackedCleanDependencyStatus({ trackedStatus: 0, dirtyStatus: " M uv.lock", paths: ["uv.lock"] }),
    /committed and clean/,
  );
});

test("schema-3 onedir manifest validation and reuse reject provenance drift", () => {
  const manifest = validManifest();
  assert.deepEqual(validateReleaseManifest(manifest), []);
  assert.equal(releaseProvenanceMatches(manifest, manifest), true);
  assert.equal(releaseProvenanceMatches(manifest, { ...manifest, lockSha256: "9".repeat(64) }), false);
  assert.equal(releaseProvenanceMatches(manifest, { ...manifest, acceleratorProfile: "directml" }), false);
  assert.match(validateReleaseManifest({ ...manifest, pythonVersion: "3.13.0" }).join("; "), /Python 3\.12/);
  assert.match(validateReleaseManifest({ ...manifest, capabilityExtras: ["core"] }).join("; "), /capabilityExtras/);
});

test("binary reuse verifies both size and SHA-256", async () => {
  const tempDir = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-release-manifest-"));
  const binaryPath = path.join(tempDir, "backend.bin");
  try {
    await fsp.writeFile(binaryPath, "locked backend\n", "utf8");
    const stat = await fsp.stat(binaryPath);
    const manifest = validManifest({ binarySize: stat.size, binarySha256: await sha256File(binaryPath) });
    assert.equal(await binaryMatchesManifest(binaryPath, manifest), true);
    await fsp.appendFile(binaryPath, "tampered\n", "utf8");
    assert.equal(await binaryMatchesManifest(binaryPath, manifest), false);
  } finally {
    await fsp.rm(tempDir, { recursive: true, force: true });
  }
});

test("onedir reuse verifies every staged backend entry", async () => {
  const tempDir = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-release-onedir-"));
  const backendEntryPoint = process.platform === "win32" ? "edmg-studio-backend.exe" : "edmg-studio-backend";
  const launcherPath = path.join(tempDir, backendEntryPoint);
  const runtimePath = path.join(tempDir, "_internal", "torch-runtime.bin");
  try {
    await fsp.mkdir(path.dirname(runtimePath), { recursive: true });
    await fsp.writeFile(launcherPath, "launcher\n", "utf8");
    await fsp.writeFile(runtimePath, "runtime\n", "utf8");
    const bundleEntries = await collectBundleEntries(tempDir);
    const launcher = bundleEntries.find((entry) => entry.path === backendEntryPoint);
    const manifest = validManifest({
      backendEntryPoint,
      bundleEntries,
      bundleEntryCount: bundleEntries.length,
      bundleFileCount: bundleEntries.filter((entry) => entry.type === "file").length,
      bundleSize: bundleEntries
        .filter((entry) => entry.type === "file")
        .reduce((total, entry) => total + entry.size, 0),
      binarySize: launcher.size,
      binarySha256: launcher.sha256,
    });
    assert.deepEqual(validateReleaseManifest(manifest), []);
    assert.equal(await bundleMatchesManifest(tempDir, manifest), true);
    await fsp.appendFile(runtimePath, "tampered\n", "utf8");
    assert.equal(await bundleMatchesManifest(tempDir, manifest), false);
    await fsp.writeFile(path.join(tempDir, "unexpected.txt"), "extra\n", "utf8");
    assert.equal(await bundleMatchesManifest(tempDir, manifest), false);
  } finally {
    await fsp.rm(tempDir, { recursive: true, force: true });
  }
});

test("supported release paths contain no pip or venv build fallback", () => {
  const prepare = fs.readFileSync(path.join(__dirname, "prepare-release-bundle.mjs"), "utf8");
  const windowsBuild = fs.readFileSync(path.join(studioRoot, "packaging", "windows", "build_all.ps1"), "utf8");
  const gitignore = fs.readFileSync(path.resolve(studioRoot, "..", "..", ".gitignore"), "utf8");
  const pyinstallerSupport = fs.readFileSync(path.join(studioRoot, "python_backend", "pyinstaller_support.py"), "utf8");
  const pyinstallerSpec = fs.readFileSync(path.join(studioRoot, "python_backend", "pyinstaller.spec"), "utf8");
  assert.doesNotMatch(prepare, /(?:-m\s+pip|pip\s+install|-m\s+venv)/i);
  assert.doesNotMatch(windowsBuild, /(?:-m\s+pip|pip\s+install|-m\s+venv)/i);
  assert.doesNotMatch(pyinstallerSupport, /nltk\.download\s*\(/);
  assert.match(pyinstallerSpec, /upx=False/);
  assert.match(pyinstallerSpec, /exclude_binaries=True/);
  assert.match(pyinstallerSpec, /COLLECT\s*\(/);
  assert.match(gitignore, /electron-resources\/backend\/\*/);
  assert.match(gitignore, /!studio\/edmg-studio\/electron-resources\/backend\/\.gitkeep/);
});

test("Director release stages a self-contained production hoisted install", () => {
  const prepare = fs.readFileSync(path.join(__dirname, "prepare-release-bundle.mjs"), "utf8");
  assert.match(prepare, /"--prod"/);
  assert.match(prepare, /"--frozen-lockfile"/);
  assert.match(prepare, /"--config\.node-linker=hoisted"/);
  assert.match(prepare, /"--config\.package-import-method=copy"/);
  assert.match(prepare, /inspectDirectorDependencyTree/);
  assert.match(prepare, /load staged director entrypoint/);
  assert.match(prepare, /await import/);
  assert.doesNotMatch(prepare, /const copyEntries = \[[^\]]*"node_modules"/s);
});

test("package release commands select explicit profiles without changing pnpm", () => {
  const packageJson = JSON.parse(fs.readFileSync(path.join(studioRoot, "package.json"), "utf8"));
  assert.equal(packageJson.packageManager, "pnpm@10.33.0");
  for (const profile of ["cpu", "directml", "cuda"]) {
    assert.equal(
      packageJson.scripts[`prepare:release-bundle:${profile}`],
      `node scripts/prepare-release-bundle.mjs --profile ${profile}`,
    );
  }
  assert.match(packageJson.scripts["dist:win:cpu"], /prepare:release-bundle:cpu/);
  assert.match(packageJson.scripts["dist:win:directml"], /prepare:release-bundle:directml/);
  assert.match(packageJson.scripts["dist:win:cuda"], /dist:win:cuda:dir/);
  assert.match(packageJson.scripts["dist:win:cuda"], /build_inno_external\.ps1/);
  assert.match(packageJson.scripts["dist:win:cuda"], /--profile cuda/);
  assert.match(packageJson.scripts["dist:win:cuda"], /--artifact-set win-inno-cuda/);
  assert.match(packageJson.scripts["dist:win:cuda:dir"], /prepare:release-bundle:cuda/);
  assert.match(packageJson.scripts["dist:win:cuda:nsis"], /prepare:release-bundle:cuda/);
  assert.match(packageJson.scripts["dist:linux"], /prepare:release-bundle:cpu/);
  assert.match(packageJson.scripts["dist:linux:cuda"], /prepare:release-bundle:cuda/);
});

test("Inno external installer tracks extracted payload files for safe uninstall", () => {
  const innoBuild = fs.readFileSync(
    path.join(studioRoot, "packaging", "windows", "build_inno_external.ps1"),
    "utf8",
  );
  assert.match(innoBuild, /VER < EncodeVer\(7,0,0\)/);
  assert.match(innoBuild, /ArchiveExtraction=enhanced\/nopassword/);
  assert.match(innoBuild, /PayloadExpandedSize/);
  assert.match(innoBuild, /Security\.Cryptography\.SHA256\]::Create/);
  assert.doesNotMatch(innoBuild, /Get-FileHash/);
  assert.match(innoBuild, /ExternalSize: \{0\}; Hash: "\{1\}"/);
  assert.match(innoBuild, /\[InstallDelete\]/);
  assert.match(innoBuild, /Type: filesandordirs; Name: "\{app\}\\resources\\backend"/);
  assert.doesNotMatch(innoBuild, /Type: filesandordirs; Name: "\{app\}"/);
  assert.match(innoBuild, /external extractarchive recursesubdirs createallsubdirs ignoreversion/);
  assert.doesNotMatch(innoBuild, /\[UninstallDelete\]/);
  assert.doesNotMatch(innoBuild, /\{app\}\\\*/);
  assert.doesNotMatch(innoBuild, /payload\\tools\\7zip/);
});
