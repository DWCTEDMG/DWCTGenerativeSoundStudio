import assert from "node:assert/strict";
import fs from "node:fs";
import fsp from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import {
  assertValidReleaseManifest,
  resolveAcceleratorProfile,
  sha256File,
} from "./release-python-toolchain.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const expectedLandmarks = Object.freeze(["Workspace", "Render", "Models", "Settings", "Setup"]);

function log(message) {
  console.log(`[packaged-appimage-smoke] ${message}`);
}

async function readJson(filePath) {
  return JSON.parse(await fsp.readFile(filePath, "utf8"));
}

export function resolveCurrentAppImage(distDir, version, entries = null) {
  const names = entries ?? (fs.existsSync(distDir) ? fs.readdirSync(distDir) : []);
  const candidates = names
    .filter((name) => name.toLowerCase().endsWith(".appimage"))
    .filter((name) => name.includes(version))
    .map((name) => path.join(distDir, name));
  if (candidates.length !== 1) {
    throw new Error(
      `Expected exactly one EDMG Studio ${version} AppImage in ${distDir}; found ${candidates.length}: ${candidates.join(", ") || "none"}`,
    );
  }
  return candidates[0];
}

async function reserveBackendPort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    server.close();
    throw new Error("Unable to reserve a local backend port.");
  }
  await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
  return address.port;
}

async function waitForJsonFile(filePath, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const stat = await fsp.stat(filePath);
      if (stat.size > 0) return await readJson(filePath);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Timed out waiting for valid JSON at ${filePath}${lastError ? `: ${lastError.message}` : ""}`);
}

async function fetchJsonWithRetry(url, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(2000) });
      const body = await response.text();
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${body}`);
      return body ? JSON.parse(body) : {};
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }
  throw new Error(`Timed out waiting for ${url}: ${lastError?.message || "unknown error"}`);
}

async function waitForBackendShutdown(baseUrl, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await fetch(`${baseUrl}/health`, { signal: AbortSignal.timeout(750) });
    } catch {
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  return false;
}

function launchPlan(appImage) {
  const appArgs = typeof process.getuid === "function" && process.getuid() === 0 ? ["--no-sandbox"] : [];
  const hasGraphicalSession = Boolean(process.env.DISPLAY || process.env.WAYLAND_DISPLAY);
  if (!hasGraphicalSession) {
    const xvfb = "/usr/bin/xvfb-run";
    if (!fs.existsSync(xvfb)) {
      throw new Error("No DISPLAY/WAYLAND session is available and /usr/bin/xvfb-run is missing.");
    }
    return { command: xvfb, args: ["-a", appImage, ...appArgs], graphicalMode: "xvfb" };
  }
  return { command: appImage, args: appArgs, graphicalMode: process.env.WAYLAND_DISPLAY ? "wayland" : "x11" };
}

async function terminateProcessGroup(child, exitPromise) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  try {
    process.kill(-child.pid, "SIGTERM");
  } catch (error) {
    if (error.code !== "ESRCH") throw error;
  }
  const exited = await Promise.race([
    exitPromise.then(() => true),
    new Promise((resolve) => setTimeout(() => resolve(false), 8000)),
  ]);
  if (exited) return;
  try {
    process.kill(-child.pid, "SIGKILL");
  } catch (error) {
    if (error.code !== "ESRCH") throw error;
  }
  await Promise.race([exitPromise, new Promise((resolve) => setTimeout(resolve, 3000))]);
}

async function main() {
  if (process.platform !== "linux") {
    throw new Error(`Final AppImage smoke must run on Linux; current platform is ${process.platform}.`);
  }

  const packageJson = await readJson(path.join(root, "package.json"));
  const version = String(packageJson.version || "").trim();
  assert.ok(version, "package.json version is required");
  const profile = resolveAcceleratorProfile({ argv: [], env: process.env, platform: process.platform });
  assert.ok(["cpu", "cuda"].includes(profile), `Linux AppImage profile must be cpu or cuda; received ${profile}`);

  const appImage = resolveCurrentAppImage(path.join(root, "dist"), version);
  const stat = await fsp.stat(appImage);
  await fsp.chmod(appImage, stat.mode | 0o111);
  const fileResult = spawnSync("file", ["--brief", appImage], { encoding: "utf8", shell: false });
  if (fileResult.error) throw fileResult.error;
  assert.equal(fileResult.status, 0, `file inspection failed: ${fileResult.stderr || fileResult.stdout}`);
  const fileDescription = String(fileResult.stdout || "").trim();
  assert.match(fileDescription, /ELF 64-bit/i, `AppImage must be a 64-bit ELF executable: ${fileDescription}`);
  assert.match(fileDescription, /x86-64|x86_64/i, `AppImage must target x86_64: ${fileDescription}`);

  const stagedBackendRoot = path.join(root, "release", "staged-app", "electron-resources", "backend");
  const manifestPath = path.join(stagedBackendRoot, "backend-bundle-manifest.json");
  assert.ok(fs.existsSync(manifestPath), `Staged backend manifest is missing: ${manifestPath}`);
  const manifest = await readJson(manifestPath);
  assertValidReleaseManifest(manifest);
  assert.equal(manifest.platform, "linux", "Final AppImage must be built from a Linux backend bundle.");
  assert.equal(manifest.acceleratorProfile, profile, "Final AppImage backend profile must match the requested smoke profile.");
  for (const binaryName of ["ffmpeg", "ffprobe"]) {
    const binaryPath = path.join(root, "release", "staged-app", "electron-resources", "bin", binaryName);
    assert.ok(fs.existsSync(binaryPath), `Final Linux package staging is missing bundled ${binaryName}: ${binaryPath}`);
  }

  const evidenceDir = path.join(root, "release", "evidence");
  await fsp.mkdir(evidenceDir, { recursive: true });
  const rendererReportPath = path.join(evidenceDir, "linux-appimage-renderer-probe.json");
  const summaryPath = path.join(evidenceDir, "linux-appimage-smoke.json");
  const logPath = path.join(evidenceDir, "linux-appimage-smoke.log");
  await Promise.all([
    fsp.rm(rendererReportPath, { force: true }),
    fsp.rm(summaryPath, { force: true }),
    fsp.rm(logPath, { force: true }),
  ]);

  const fixtureRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-appimage-smoke-"));
  const fixtureDir = path.join(fixtureRoot, "frames");
  const fixtureFile = path.join(fixtureRoot, "demo.txt");
  const tempDir = path.join(fixtureRoot, "tmp");
  await Promise.all([
    fsp.mkdir(fixtureDir, { recursive: true }),
    fsp.mkdir(tempDir, { recursive: true }),
    fsp.mkdir(path.join(fixtureRoot, "xdg-config"), { recursive: true }),
    fsp.mkdir(path.join(fixtureRoot, "xdg-cache"), { recursive: true }),
    fsp.mkdir(path.join(fixtureRoot, "xdg-data"), { recursive: true }),
    fsp.mkdir(path.join(fixtureRoot, "xdg-state"), { recursive: true }),
    fsp.writeFile(fixtureFile, "final AppImage Studio UI probe\n", "utf8"),
  ]);

  const backendPort = await reserveBackendPort();
  const backendUrl = `http://127.0.0.1:${backendPort}`;
  const plan = launchPlan(appImage);
  const logHandle = await fsp.open(logPath, "w");
  const childEnv = {
    ...process.env,
    APPIMAGE_EXTRACT_AND_RUN: "1",
    EDMG_AI_PROVIDER: "rule_based",
    EDMG_BACKEND_ACCELERATOR_PROFILE: profile,
    EDMG_DIRECTOR_SPAWN: "0",
    EDMG_STUDIO_BACKEND_HOST: "127.0.0.1",
    EDMG_STUDIO_BACKEND_MODE: "managed",
    EDMG_STUDIO_BACKEND_PORT: String(backendPort),
    EDMG_STUDIO_BACKEND_READY_TIMEOUT_MS: "180000",
    EDMG_STUDIO_BACKEND_URL: "",
    EDMG_STUDIO_SPAWN_BACKEND: "1",
    EDMG_STUDIO_HOME: path.join(fixtureRoot, "studio-home"),
    EDMG_STUDIO_TEST_EXPECT_BACKEND_URL: backendUrl,
    EDMG_STUDIO_TEST_FAKE_PATH_ACTIONS: "1",
    EDMG_STUDIO_TEST_MODE: "1",
    EDMG_STUDIO_TEST_PROBE_OPEN_PATH: fixtureDir,
    EDMG_STUDIO_TEST_PROBE_REVEAL_PATH: fixtureFile,
    EDMG_STUDIO_TEST_REPORT_PATH: rendererReportPath,
    EDMG_STUDIO_TEST_SKIP_MIGRATION: "1",
    ELECTRON_DISABLE_SECURITY_WARNINGS: "1",
    TMPDIR: tempDir,
    XDG_CACHE_HOME: path.join(fixtureRoot, "xdg-cache"),
    XDG_CONFIG_HOME: path.join(fixtureRoot, "xdg-config"),
    XDG_DATA_HOME: path.join(fixtureRoot, "xdg-data"),
    XDG_STATE_HOME: path.join(fixtureRoot, "xdg-state"),
  };
  delete childEnv.EDMG_STUDIO_TEST_PAGE;

  log(`launching ${path.basename(appImage)} with the packaged ${profile} backend using ${plan.graphicalMode}`);
  const child = spawn(plan.command, plan.args, {
    cwd: path.dirname(appImage),
    detached: true,
    env: childEnv,
    shell: false,
    stdio: ["ignore", logHandle.fd, logHandle.fd],
  });
  const exitPromise = new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code, signal) => resolve({ code, signal }));
  });

  let rendererReport;
  let endpoints;
  let backendStopped = false;
  try {
    rendererReport = await Promise.race([
      waitForJsonFile(rendererReportPath, 210000),
      exitPromise.then(({ code, signal }) => {
        throw new Error(`AppImage exited before producing its renderer report (code=${code}, signal=${signal}). See ${logPath}`);
      }),
    ]);
    assert.equal(rendererReport.ok, true, `Production renderer probe failed: ${JSON.stringify(rendererReport)}`);
    assert.equal(rendererReport.expectProductionUi, true, "Final AppImage smoke must load the production React renderer.");
    assert.equal(rendererReport.rendererProtocol, "file:", `Unexpected renderer protocol: ${rendererReport.rendererProtocol}`);
    assert.ok(String(rendererReport.bodyText || "").trim(), "Production renderer body must not be empty.");
    assert.deepEqual(rendererReport.uiLandmarks?.expected, [...expectedLandmarks]);
    assert.deepEqual(rendererReport.uiLandmarks?.missing, []);
    assert.equal(rendererReport.backendUrlSync, backendUrl);
    assert.equal(rendererReport.backendUrlAsync, backendUrl);
    assert.equal(rendererReport.reveal?.ok, true);
    assert.equal(rendererReport.open?.ok, true);

    endpoints = {
      health: await fetchJsonWithRetry(`${backendUrl}/health`),
      config: await fetchJsonWithRetry(`${backendUrl}/v1/config`),
      setup: await fetchJsonWithRetry(`${backendUrl}/v1/setup/status`),
    };
    assert.equal(endpoints.health?.ok, true, "Packaged backend health response must be ok.");
  } finally {
    await terminateProcessGroup(child, exitPromise);
    await logHandle.close();
    backendStopped = await waitForBackendShutdown(backendUrl);
    await fsp.rm(fixtureRoot, { recursive: true, force: true });
  }
  assert.equal(backendStopped, true, `Packaged backend still answered after AppImage shutdown: ${backendUrl}`);

  const finalStat = await fsp.stat(appImage);
  const summary = {
    ok: true,
    generatedAt: new Date().toISOString(),
    appImage: {
      path: path.relative(root, appImage).split(path.sep).join("/"),
      bytes: finalStat.size,
      sha256: await sha256File(appImage),
      fileDescription,
      version,
      platform: "linux",
      architecture: "x64",
      acceleratorProfile: profile,
    },
    graphicalMode: plan.graphicalMode,
    rootNoSandboxApplied: plan.args.includes("--no-sandbox"),
    backendUrl,
    backendStopped,
    endpoints,
    rendererReport,
    logPath: path.relative(root, logPath).split(path.sep).join("/"),
  };
  await fsp.writeFile(summaryPath, `${JSON.stringify(summary, null, 2)}\n`, "utf8");
  log(`final AppImage, packaged backend, and production Studio UI passed; evidence: ${summaryPath}`);
  console.log(JSON.stringify(summary, null, 2));
}

function isMainModule() {
  if (!process.argv[1]) return false;
  return path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
}

if (isMainModule()) {
  main().catch((error) => {
    console.error("[packaged-appimage-smoke] FAILED", error);
    process.exitCode = 1;
  });
}
