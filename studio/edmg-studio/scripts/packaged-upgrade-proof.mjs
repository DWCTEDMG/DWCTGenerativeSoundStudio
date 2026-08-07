import assert from "node:assert/strict";
import fs from "node:fs";
import fsp from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

import {
  INSTALLED_APP_DIR_ENV,
  assertCandidateVersionIsNewer,
  assertInstalledAppBaselineUnchanged,
  assertPathOutsideInstalledAppBaseline,
  inspectInstalledAppBaseline,
  inspectPackagedAppCandidate,
  resolveInstalledAppDir,
} from "./packaged-upgrade-proof-lib.mjs";
import {
  buildHermeticPackagedProofEnv,
  resolveHermeticProofProfile,
} from "./packaged-proof-environment.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");

function log(message) {
  console.log(`[packaged-upgrade-proof] ${message}`);
}

function resolvePackagedApp() {
  const envPath = process.env.EDMG_STUDIO_PACKAGED_APP;
  if (envPath && fs.existsSync(envPath)) return envPath;
  const candidate = path.join(root, "dist", "win-unpacked", process.platform === "win32" ? "EDMG Studio.exe" : "EDMG Studio");
  return fs.existsSync(candidate) ? candidate : "";
}

function chooseHomeRoot() {
  const preferred = process.env.EDMG_STUDIO_PROOF_ROOT;
  if (preferred) return preferred;
  return os.tmpdir();
}

function chooseLegacyRoot(stamp) {
  return path.join(chooseHomeRoot(), `EDMG-Legacy-Proof-${stamp}`);
}

function buildPathSet(studioHome) {
  const electronDir = path.join(studioHome, "electron");
  return {
    studioHome,
    dataDir: path.join(studioHome, "data"),
    modelsDir: path.join(studioHome, "models"),
    cacheRoot: path.join(studioHome, "cache"),
    logsDir: path.join(studioHome, "logs"),
    externalDir: path.join(studioHome, "external"),
    electronUserData: electronDir,
    sessionData: path.join(electronDir, "session"),
  };
}

async function allocatePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.listen(0, "127.0.0.1", () => resolve());
    server.on("error", reject);
  });
  const address = server.address();
  server.close();
  if (!address || typeof address === "string") throw new Error("Unable to allocate backend port");
  return address.port;
}

async function stopExistingPackagedProcesses() {
  if (process.platform !== "win32") return;
  const appDir = path.join(root, "dist", "win-unpacked").replace(/'/g, "''");
  const command = `$ErrorActionPreference='SilentlyContinue'; $appDir='${appDir}'; Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($appDir, [System.StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }`;
  await new Promise((resolve, reject) => {
    const child = spawn("powershell", ["-NoProfile", "-Command", command], { stdio: "ignore" });
    child.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`Failed to stop stale packaged processes: ${code}`))));
    child.on("error", reject);
  });
  await new Promise((resolve) => setTimeout(resolve, 1500));
}

async function waitForHealth(baseUrl, timeoutMs = 120000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      return await requestJson(`${baseUrl}/health`);
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 750));
    }
  }
  throw new Error(`Backend never became healthy at ${baseUrl}`);
}

async function requestJson(url, init = {}) {
  const response = await fetch(url, {
    ...init,
    headers: {
      accept: "application/json",
      ...(init.headers || {}),
    },
  });
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { raw: text };
    }
  }
  if (!response.ok) {
    throw new Error(`${init.method || "GET"} ${url} failed: ${response.status} ${text}`);
  }
  return payload;
}

async function killProcessTree(child) {
  if (!child || child.exitCode !== null) return;
  if (process.platform === "win32") {
    await new Promise((resolve) => {
      const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
      killer.on("exit", () => resolve());
      killer.on("error", () => resolve());
    });
    return;
  }
  child.kill("SIGTERM");
}

async function seedLegacyArtifacts(paths) {
  const fixtures = [
    { root: paths.dataDir, relative: path.join("projects", "legacy-proof.txt"), content: "legacy project data\n" },
    { root: paths.modelsDir, relative: path.join("checkpoints", "legacy-model.txt"), content: "legacy model placeholder\n" },
    { root: paths.cacheRoot, relative: path.join("tmp", "legacy-cache.txt"), content: "legacy cache entry\n" },
    { root: paths.logsDir, relative: "legacy.log", content: "legacy log entry\n" },
    { root: paths.externalDir, relative: path.join("bin", "legacy-tool.txt"), content: "legacy external tool marker\n" },
    { root: paths.electronUserData, relative: path.join("Default", "legacy-electron.txt"), content: "legacy electron data\n" },
  ];

  for (const fixture of fixtures) {
    const target = path.join(fixture.root, fixture.relative);
    await fsp.mkdir(path.dirname(target), { recursive: true });
    await fsp.writeFile(target, fixture.content, "utf8");
  }

  return fixtures.map((fixture) => ({
    label: path.relative(paths.studioHome, path.join(fixture.root, fixture.relative)),
    relative: fixture.relative,
    rootKey:
      fixture.root === paths.dataDir ? "dataDir"
        : fixture.root === paths.modelsDir ? "modelsDir"
          : fixture.root === paths.cacheRoot ? "cacheRoot"
            : fixture.root === paths.logsDir ? "logsDir"
              : fixture.root === paths.externalDir ? "externalDir"
                : "electronUserData",
    content: fixture.content,
  }));
}

async function main() {
  const installedAppDir = resolveInstalledAppDir({ argv: process.argv.slice(2) });
  const installedBaselineBefore = installedAppDir
    ? await inspectInstalledAppBaseline(installedAppDir)
    : null;
  if (installedBaselineBefore) {
    log(`validated read-only installed baseline ${installedBaselineBefore.appDir}`);
  }

  const appExe = resolvePackagedApp();
  assert.ok(appExe, "Packaged app not found. Run pnpm run dist:win first or set EDMG_STUDIO_PACKAGED_APP.");

  let candidateEvidence = null;
  let versionComparison = null;
  if (installedBaselineBefore) {
    await assertPathOutsideInstalledAppBaseline(
      installedBaselineBefore.appDir,
      appExe,
      "Packaged candidate executable",
    );
    candidateEvidence = await inspectPackagedAppCandidate(appExe);
    versionComparison = assertCandidateVersionIsNewer(installedBaselineBefore, candidateEvidence);
    log(
      `candidate ${versionComparison.candidateVersion} is newer than installed baseline `
      + versionComparison.installedBaselineVersion,
    );
  }

  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "").replace("T", "_");
  const homeRoot = chooseHomeRoot();
  const targetHome = path.join(homeRoot, `EDMG-Upgraded-Proof-${stamp}`);
  const legacyHome = chooseLegacyRoot(stamp);
  const { appDataDir, localAppDataDir, bootstrapDir, bootstrapPath } = resolveHermeticProofProfile(targetHome);
  const testPage = path.join(targetHome, "blank.html");
  const port = Number(process.env.EDMG_STUDIO_PROOF_PORT || (await allocatePort()));
  const baseUrl = `http://127.0.0.1:${port}`;
  const source = buildPathSet(legacyHome);
  const target = buildPathSet(targetHome);

  if (installedBaselineBefore) {
    for (const [label, mutablePath] of [
      ["Upgrade-proof target Studio home", targetHome],
      ["Upgrade-proof legacy Studio home", legacyHome],
      ["Upgrade-proof bootstrap directory", bootstrapDir],
      ["Upgrade-proof bootstrap file", bootstrapPath],
      ["Upgrade-proof test page", testPage],
    ]) {
      await assertPathOutsideInstalledAppBaseline(installedBaselineBefore.appDir, mutablePath, label);
    }
  }

  let child = null;
  let cleanupPackagedProcesses = false;
  let summary = null;
  let primaryError = null;
  try {
    cleanupPackagedProcesses = true;
    await stopExistingPackagedProcesses();

    await fsp.mkdir(targetHome, { recursive: true });
    await fsp.mkdir(bootstrapDir, { recursive: true });
    await fsp.mkdir(localAppDataDir, { recursive: true });
    await fsp.writeFile(testPage, "<!doctype html><html><body>packaged upgrade proof</body></html>\n");

    const seeded = await seedLegacyArtifacts(source);
    const bootstrap = {
      studioHome: targetHome,
      pendingMigration: {
        requestedAt: new Date().toISOString(),
        source,
        target,
      },
      updatedAt: new Date().toISOString(),
    };
    await fsp.writeFile(bootstrapPath, JSON.stringify(bootstrap, null, 2) + "\n", "utf8");

    const launchEnv = buildHermeticPackagedProofEnv({
      studioHome: targetHome,
      port,
      testPage,
    });
    delete launchEnv[INSTALLED_APP_DIR_ENV];

    log(`launching candidate ${appExe}`);
    child = spawn(appExe, [], {
      cwd: path.dirname(appExe),
      env: launchEnv,
      stdio: "ignore",
    });

    const health = await waitForHealth(baseUrl);
    const config = await requestJson(`${baseUrl}/v1/config`);
    const bootstrapAfter = JSON.parse(await fsp.readFile(bootstrapPath, "utf8"));
    const migration = bootstrapAfter?.lastMigration ?? null;

    assert.equal(config?.studio_home, targetHome, "Packaged backend should resolve to the target Studio home after migration");
    assert.equal(config?.data_dir, target.dataDir, "Packaged backend should resolve to the migrated data dir");
    assert.equal(Boolean(bootstrapAfter?.pendingMigration), false, "Pending migration should be cleared after launch");
    assert.equal(Boolean(migration?.ok), true, "Last migration summary should report success");

    for (const fixture of seeded) {
      const targetRoot = target[fixture.rootKey];
      const expectedPath = path.join(targetRoot, fixture.relative);
      assert.equal(fs.existsSync(expectedPath), true, `Migrated artifact missing: ${expectedPath}`);
      const content = await fsp.readFile(expectedPath, "utf8");
      assert.equal(content, fixture.content, `Migrated artifact content mismatch: ${expectedPath}`);
    }

    const failedResults = Array.isArray(migration?.results) ? migration.results.filter((entry) => entry?.status === "failed") : [];
    assert.equal(failedResults.length, 0, `Upgrade migration reported failures: ${JSON.stringify(failedResults)}`);

    summary = {
      ok: true,
      baseUrl,
      health,
      legacyHome,
      targetHome,
      appDataDir,
      localAppDataDir,
      bootstrapPath,
      config: {
        studioHome: config?.studio_home ?? null,
        dataDir: config?.data_dir ?? null,
        modelsDir: config?.models_dir ?? null,
        logsDir: config?.logs_dir ?? null,
        externalDir: config?.external_dir ?? null,
      },
      migration: {
        ok: migration?.ok ?? false,
        requestedAt: migration?.requestedAt ?? null,
        completedAt: migration?.completedAt ?? null,
        resultLabels: Array.isArray(migration?.results) ? migration.results.map((entry) => `${entry.label}:${entry.status}`) : [],
      },
      seededArtifacts: seeded.map((fixture) => ({
        label: fixture.label,
        migratedTo: path.join(target[fixture.rootKey], fixture.relative),
      })),
    };
    if (installedBaselineBefore) {
      summary.upgradeEvidence = {
        schemaVersion: 1,
        installedBaseline: installedBaselineBefore,
        candidate: candidateEvidence,
        versionComparison,
        installedBaselineUnchangedAfterProof: false,
      };
    }
  } catch (error) {
    primaryError = error;
  }

  const cleanupErrors = [];
  const attemptCleanup = async (label, action) => {
    try {
      await action();
    } catch (error) {
      cleanupErrors.push(new Error(`${label}: ${error.message}`, { cause: error }));
    }
  };
  await attemptCleanup("stop launched candidate process tree", () => killProcessTree(child));
  if (cleanupPackagedProcesses) {
    await attemptCleanup("stop residual packaged candidate processes", () => stopExistingPackagedProcesses());
  }
  if (installedBaselineBefore) {
    await attemptCleanup("verify read-only installed baseline integrity", async () => {
      const installedBaselineAfter = await inspectInstalledAppBaseline(installedBaselineBefore.appDir);
      assertInstalledAppBaselineUnchanged(installedBaselineBefore, installedBaselineAfter);
      if (summary?.upgradeEvidence) {
        summary.upgradeEvidence.installedBaselineUnchangedAfterProof = true;
        summary.upgradeEvidence.verifiedAfter = installedBaselineAfter.capturedAt;
      }
    });
  }

  const errors = primaryError ? [primaryError, ...cleanupErrors] : cleanupErrors;
  if (errors.length === 1) throw errors[0];
  if (errors.length > 1) {
    throw new AggregateError(errors, "Packaged upgrade proof failed and one or more cleanup/integrity checks also failed");
  }

  console.log(JSON.stringify(summary, null, 2));
}

main().catch((error) => {
  console.error("[packaged-upgrade-proof] FAILED", error);
  process.exit(1);
});
