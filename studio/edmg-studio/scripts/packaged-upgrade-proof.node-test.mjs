import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import fsp from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  INSTALLED_APP_DIR_ENV,
  assertCandidateVersionIsNewer,
  assertInstalledAppBaselineUnchanged,
  assertPathOutsideInstalledAppBaseline,
  compareNumericVersions,
  inspectInstalledAppBaseline,
  inspectPackagedAppCandidate,
  resolveInstalledAppDir,
} from "./packaged-upgrade-proof-lib.mjs";
import {
  TEST_BOOTSTRAP_CONFIG_PATH_ENV,
  buildHermeticPackagedProofEnv,
  buildStudioProofPaths,
  resolveHermeticProofProfile,
} from "./packaged-proof-environment.mjs";

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function fakeVersion(version) {
  return {
    fileVersion: version,
    productVersion: `${version}.0`,
    productName: "EDMG Studio",
    companyName: "Dwct",
  };
}

test("packaged proofs replace hostile inherited storage and backend settings with an isolated profile", () => {
  const studioHome = path.resolve("proof-root", "studio-home");
  const testPage = path.join(studioHome, "probe.html");
  const paths = buildStudioProofPaths(studioHome);
  const profile = resolveHermeticProofProfile(studioHome);
  const environment = buildHermeticPackagedProofEnv({
    baseEnv: {
      APPDATA: "C:\\Users\\real\\AppData\\Roaming",
      LOCALAPPDATA: "C:\\Users\\real\\AppData\\Local",
      EDMG_STUDIO_HOME: "G:\\real-studio-home",
      EDMG_STUDIO_DATA_DIR: "G:\\real-data",
      EDMG_STUDIO_MODELS_DIR: "G:\\real-models",
      EDMG_STUDIO_CACHE_DIR: "G:\\real-cache",
      EDMG_STUDIO_BACKEND_MODE: "external",
      EDMG_STUDIO_SPAWN_BACKEND: "0",
      EDMG_STUDIO_BACKEND_URL: "https://remote.example.invalid",
      EDMG_BACKEND_AUTH_TOKEN: "real-secret",
      [TEST_BOOTSTRAP_CONFIG_PATH_ENV]: "C:\\Users\\real\\AppData\\Roaming\\EDMG Studio\\bootstrap.json",
      [INSTALLED_APP_DIR_ENV]: "C:\\Program Files\\EDMG Studio",
    },
    studioHome,
    port: 17863,
    testPage,
  });

  assert.equal(environment.APPDATA, profile.appDataDir);
  assert.equal(environment.LOCALAPPDATA, profile.localAppDataDir);
  assert.equal(environment.EDMG_STUDIO_HOME, paths.studioHome);
  assert.equal(environment.EDMG_STUDIO_DATA_DIR, paths.dataDir);
  assert.equal(environment.EDMG_STUDIO_MODELS_DIR, paths.modelsDir);
  assert.equal(environment.EDMG_STUDIO_CACHE_DIR, paths.cacheRoot);
  assert.equal(environment.EDMG_STUDIO_BACKEND_MODE, "managed");
  assert.equal(environment.EDMG_STUDIO_SPAWN_BACKEND, "1");
  assert.equal(environment.EDMG_STUDIO_BACKEND_URL, "http://127.0.0.1:17863");
  assert.equal(environment.EDMG_BACKEND_AUTH_TOKEN, "");
  assert.equal(environment.EDMG_DIRECTOR_SPAWN, "0");
  assert.equal(environment.EDMG_AI_PROVIDER, "rule_based");
  assert.equal(environment[TEST_BOOTSTRAP_CONFIG_PATH_ENV], profile.bootstrapPath);
  assert.equal(environment[INSTALLED_APP_DIR_ENV], undefined);
  assert.equal(environment.TEMP.startsWith(paths.cacheRoot), true);
  assert.equal(environment.HF_HOME.startsWith(paths.cacheRoot), true);
});

test("proof-specific AI settings may change without overriding hermetic storage or backend ownership", () => {
  const studioHome = path.resolve("proof-root", "zero-state");
  const environment = buildHermeticPackagedProofEnv({
    baseEnv: {},
    studioHome,
    port: 27863,
    testPage: path.join(studioHome, "probe.html"),
    extraEnv: {
      EDMG_AI_PROVIDER: "ollama",
      EDMG_AI_OLLAMA_URL: "http://127.0.0.1:11434",
      EDMG_STUDIO_HOME: "G:\\escape",
      EDMG_STUDIO_BACKEND_URL: "https://remote.example.invalid",
      [TEST_BOOTSTRAP_CONFIG_PATH_ENV]: "G:\\escape\\bootstrap.json",
    },
  });

  assert.equal(environment.EDMG_AI_PROVIDER, "ollama");
  assert.equal(environment.EDMG_STUDIO_HOME, studioHome);
  assert.equal(environment.EDMG_STUDIO_BACKEND_URL, "http://127.0.0.1:27863");
  assert.equal(
    environment[TEST_BOOTSTRAP_CONFIG_PATH_ENV],
    resolveHermeticProofProfile(studioHome).bootstrapPath,
  );
});

async function createPackagedApp(root, { version = "1.0.0", backendContent = "backend binary\n" } = {}) {
  const executableName = process.platform === "win32" ? "EDMG Studio.exe" : "EDMG Studio";
  const backendEntryPoint = process.platform === "win32" ? "edmg-studio-backend.exe" : "edmg-studio-backend";
  const resourcesDir = path.join(root, "resources");
  const backendDir = path.join(resourcesDir, "backend");
  const executablePath = path.join(root, executableName);
  const backendPath = path.join(backendDir, backendEntryPoint);
  await fsp.mkdir(backendDir, { recursive: true });
  await Promise.all([
    fsp.writeFile(executablePath, `EDMG Studio ${version}\n`, "utf8"),
    fsp.writeFile(path.join(resourcesDir, "app.asar"), `asar ${version}\n`, "utf8"),
    fsp.writeFile(path.join(resourcesDir, "runtime-defaults.json"), "{}\n", "utf8"),
    fsp.writeFile(path.join(backendDir, "launcher_env.defaults.json"), "{}\n", "utf8"),
    fsp.writeFile(backendPath, backendContent, "utf8"),
  ]);
  const binarySize = Buffer.byteLength(backendContent);
  await fsp.writeFile(
    path.join(backendDir, "backend-bundle-manifest.json"),
    JSON.stringify({
      schemaVersion: 5,
      ok: true,
      bundleLayout: "onedir",
      backendEntryPoint,
      binarySize,
      binarySha256: sha256(backendContent),
      sourceHash: "a".repeat(64),
      acceleratorProfile: "cpu",
      pythonVersion: "3.12.10",
      uvVersion: "0.11.28",
      pyinstallerVersion: "6.21.0",
    }),
    "utf8",
  );
  return { executablePath, backendPath, version };
}

test("installed baseline path resolution is opt-in, absolute, and CLI-first", () => {
  const envPath = path.resolve("installed-from-env");
  const cliPath = path.resolve("installed-from-cli");
  assert.equal(resolveInstalledAppDir({ argv: [], env: {} }), "");
  assert.equal(
    resolveInstalledAppDir({ argv: [], env: { [INSTALLED_APP_DIR_ENV]: envPath } }),
    path.normalize(envPath),
  );
  assert.equal(
    resolveInstalledAppDir({
      argv: ["--installed-app-dir", cliPath],
      env: { [INSTALLED_APP_DIR_ENV]: envPath },
    }),
    path.normalize(cliPath),
  );
  assert.equal(
    resolveInstalledAppDir({ argv: [`--installed-app-dir=${cliPath}`], env: {} }),
    path.normalize(cliPath),
  );
  assert.throws(
    () => resolveInstalledAppDir({ argv: ["--installed-app-dir", "relative/path"], env: {} }),
    /must be an absolute path/,
  );
  assert.throws(
    () => resolveInstalledAppDir({ argv: ["--installed-app-dir"], env: {} }),
    /requires an absolute directory path/,
  );
  assert.throws(
    () => resolveInstalledAppDir({
      argv: ["--installed-app-dir", cliPath, `--installed-app-dir=${envPath}`],
      env: {},
    }),
    /may only be supplied once/,
  );
});

test("installed baseline inspection validates layout and records version and SHA-256 evidence", async () => {
  const tempRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-installed-baseline-"));
  const app = await createPackagedApp(tempRoot, { version: "1.0.0" });
  try {
    await Promise.all([
      fsp.writeFile(path.join(tempRoot, "unins000.exe"), "uninstaller executable\n", "utf8"),
      fsp.writeFile(path.join(tempRoot, "unins000.dat"), "uninstaller data\n", "utf8"),
    ]);
    const evidence = await inspectInstalledAppBaseline(tempRoot, {
      versionReader: async (executablePath) => {
        assert.equal(executablePath, await fsp.realpath(app.executablePath));
        return fakeVersion(app.version);
      },
    });
    assert.equal(evidence.mode, "read-only");
    assert.equal(evidence.version.fileVersion, "1.0.0");
    assert.equal(evidence.backend.acceleratorProfile, "cpu");
    assert.equal(evidence.files.appExecutable.sha256, sha256("EDMG Studio 1.0.0\n"));
    assert.equal(evidence.files.backendExecutable.sha256, sha256("backend binary\n"));
    assert.match(evidence.files.backendManifest.sha256, /^[a-f0-9]{64}$/);
    assert.equal(evidence.files.uninstallerExecutable.sha256, sha256("uninstaller executable\n"));
    assert.equal(evidence.files.uninstallerData.sha256, sha256("uninstaller data\n"));
  } finally {
    await fsp.rm(tempRoot, { recursive: true, force: true });
  }
});

test("installed baseline validation rejects incomplete or tampered packages", async () => {
  const tempRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-invalid-baseline-"));
  const app = await createPackagedApp(tempRoot);
  const versionReader = async () => fakeVersion(app.version);
  try {
    await fsp.appendFile(app.backendPath, "tampered\n", "utf8");
    await assert.rejects(
      inspectInstalledAppBaseline(tempRoot, { versionReader }),
      /backend executable size does not match its manifest/,
    );
    await fsp.rm(path.join(tempRoot, "resources", "runtime-defaults.json"));
    await assert.rejects(
      inspectInstalledAppBaseline(tempRoot, { versionReader }),
      /required file is missing: resources[\\/]runtime-defaults\.json/,
    );
  } finally {
    await fsp.rm(tempRoot, { recursive: true, force: true });
  }
});

test("the proof fails invalid baseline inspection before resolving or launching a candidate", async () => {
  const tempRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-baseline-fail-safe-"));
  const installedDir = path.join(tempRoot, "installed");
  const appDataDir = path.join(tempRoot, "appdata");
  const localAppDataDir = path.join(tempRoot, "localappdata");
  const proofScript = fileURLToPath(new URL("./packaged-upgrade-proof.mjs", import.meta.url));
  await fsp.mkdir(installedDir, { recursive: true });
  try {
    const result = spawnSync(process.execPath, [proofScript, "--installed-app-dir", installedDir], {
      encoding: "utf8",
      env: {
        ...process.env,
        APPDATA: appDataDir,
        LOCALAPPDATA: localAppDataDir,
        EDMG_STUDIO_PACKAGED_APP: path.join(tempRoot, "must-not-launch.exe"),
      },
      windowsHide: true,
    });
    assert.equal(result.status, 1);
    assert.match(result.stderr, /backend bundle manifest is not readable JSON/);
    assert.deepEqual(await fsp.readdir(installedDir), []);
    await assert.rejects(fsp.stat(appDataDir), { code: "ENOENT" });
    await assert.rejects(fsp.stat(localAppDataDir), { code: "ENOENT" });
  } finally {
    await fsp.rm(tempRoot, { recursive: true, force: true });
  }
});

test("upgrade evidence distinguishes candidate and enforces a strictly newer version", async () => {
  const tempRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-upgrade-versions-"));
  const installedDir = path.join(tempRoot, "installed");
  const candidateDir = path.join(tempRoot, "candidate");
  const installed = await createPackagedApp(installedDir, { version: "1.0.0", backendContent: "old backend\n" });
  const candidate = await createPackagedApp(candidateDir, { version: "1.1.0", backendContent: "new backend\n" });
  try {
    const baselineEvidence = await inspectInstalledAppBaseline(installedDir, {
      versionReader: async () => fakeVersion(installed.version),
    });
    const candidateEvidence = await inspectPackagedAppCandidate(candidate.executablePath, {
      versionReader: async () => fakeVersion(candidate.version),
    });
    assert.equal(candidateEvidence.mode, "candidate");
    assert.notEqual(
      baselineEvidence.files.appExecutable.sha256,
      candidateEvidence.files.appExecutable.sha256,
    );
    assert.deepEqual(assertCandidateVersionIsNewer(baselineEvidence, candidateEvidence), {
      rule: "candidate-version-greater-than-installed-baseline",
      installedBaselineVersion: "1.0.0",
      candidateVersion: "1.1.0",
      comparison: "newer",
      passed: true,
    });
    const sameBuild = {
      ...candidateEvidence,
      version: fakeVersion("1.0.0"),
    };
    assert.throws(
      () => assertCandidateVersionIsNewer(baselineEvidence, sameBuild),
      /same-build or downgrade migration is not release upgrade evidence/,
    );
    assert.equal(compareNumericVersions("1.1.0", "1.0.9.9"), 1);
    assert.equal(compareNumericVersions("1.1.0", "1.1.0.0"), 0);
  } finally {
    await fsp.rm(tempRoot, { recursive: true, force: true });
  }
});

test("read-only path and integrity guards fail before an installed baseline can be reused as scratch space", async () => {
  const tempRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-baseline-guard-"));
  const installedDir = path.join(tempRoot, "installed");
  const outsideDir = path.join(tempRoot, "proof-output");
  const app = await createPackagedApp(installedDir);
  try {
    await assert.rejects(
      assertPathOutsideInstalledAppBaseline(installedDir, path.join(installedDir, "proof-output"), "Proof output"),
      /must not be inside the read-only installed-app baseline/,
    );
    await assertPathOutsideInstalledAppBaseline(installedDir, outsideDir, "Proof output");

    const before = await inspectInstalledAppBaseline(installedDir, {
      versionReader: async () => fakeVersion(app.version),
    });
    const after = structuredClone(before);
    after.capturedAt = new Date(Date.now() + 1000).toISOString();
    assert.doesNotThrow(() => assertInstalledAppBaselineUnchanged(before, after));
    after.files.appExecutable.sha256 = "f".repeat(64);
    assert.throws(
      () => assertInstalledAppBaselineUnchanged(before, after),
      /baseline changed while the packaged upgrade proof was running/,
    );
  } finally {
    await fsp.rm(tempRoot, { recursive: true, force: true });
  }
});
