import assert from "node:assert/strict";
import fs from "node:fs";
import fsp from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const KEEP_PROOF_HOME = (process.env.EDMG_STUDIO_KEEP_PROOF_HOME ?? "0") === "1";

function log(message) {
  console.log(`[packaged-zero-state-setup] ${message}`);
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
  if (process.platform === "win32" && fs.existsSync("D:\\")) return "D:\\";
  return os.tmpdir();
}

function resolveBootstrapPaths() {
  const appDataDir = process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming");
  const bootstrapDir = path.join(appDataDir, "EDMG Studio");
  return {
    bootstrapDir,
    bootstrapPath: path.join(bootstrapDir, "bootstrap.json"),
  };
}

async function backupBootstrap(bootstrapPath, stamp) {
  if (!fs.existsSync(bootstrapPath)) {
    return { existed: false, backupPath: "" };
  }
  const backupPath = `${bootstrapPath}.codex-backup-${stamp}`;
  await fsp.copyFile(bootstrapPath, backupPath);
  return { existed: true, backupPath };
}

async function restoreBootstrap(bootstrapPath, backup) {
  if (backup?.existed && backup.backupPath && fs.existsSync(backup.backupPath)) {
    await fsp.mkdir(path.dirname(bootstrapPath), { recursive: true });
    await fsp.copyFile(backup.backupPath, bootstrapPath);
    await fsp.rm(backup.backupPath, { force: true });
    return;
  }
  await fsp.rm(bootstrapPath, { force: true });
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

async function postJson(url, body) {
  return requestJson(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
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

async function stopProcessesByPathPrefix(pathPrefix) {
  if (process.platform !== "win32") return;
  const escaped = pathPrefix.replace(/'/g, "''");
  const command = `$ErrorActionPreference='SilentlyContinue'; $prefix='${escaped}'; Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }`;
  await new Promise((resolve) => {
    const child = spawn("powershell", ["-NoProfile", "-Command", command], { stdio: "ignore" });
    child.on("exit", () => resolve());
    child.on("error", () => resolve());
  });
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

async function waitForTask(baseUrl, taskId, timeoutMs = 90 * 60 * 1000) {
  const deadline = Date.now() + timeoutMs;
  let lastTask = null;
  let lastStatus = null;
  while (Date.now() < deadline) {
    const status = await requestJson(`${baseUrl}/v1/setup/status`);
    lastStatus = status;
    const tasks = Array.isArray(status?.tasks) ? status.tasks : [];
    const task = tasks.find((entry) => entry.id === taskId) || lastTask;
    if (task) {
      lastTask = task;
      if (["done", "failed"].includes(String(task.status))) {
        return { status, task };
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error(`Setup task ${taskId} timed out. Last task state: ${JSON.stringify(lastTask)}. Last status: ${JSON.stringify(lastStatus)}`);
}

async function main() {
  const appExe = resolvePackagedApp();
  assert.ok(appExe, "Packaged app not found. Run npm run dist:win first or set EDMG_STUDIO_PACKAGED_APP.");

  await stopExistingPackagedProcesses();

  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "").replace("T", "_");
  const homeRoot = chooseHomeRoot();
  const studioHome = path.join(homeRoot, `EDMG-ZeroState-Proof-${stamp}`);
  const { bootstrapPath } = resolveBootstrapPaths();
  const bootstrapBackup = await backupBootstrap(bootstrapPath, stamp);
  const port = Number(process.env.EDMG_STUDIO_PROOF_PORT || (await allocatePort()));
  const ollamaUrl = process.env.EDMG_STUDIO_ZERO_STATE_OLLAMA_URL || `http://127.0.0.1:${await allocatePort()}`;
  const baseUrl = `http://127.0.0.1:${port}`;
  const testPage = path.join(studioHome, "blank.html");
  const externalDir = path.join(studioHome, "external");
  const expectedOllamaExe = path.join(externalDir, "ollama", "ollama.exe");
  const expectedSevenZip = path.join(externalDir, "bin", "7zr.exe");
  const requestedModel = process.env.EDMG_STUDIO_ZERO_STATE_MODEL || "qwen3:4b";

  await fsp.mkdir(studioHome, { recursive: true });
  await fsp.mkdir(path.dirname(bootstrapPath), { recursive: true });
  await fsp.rm(bootstrapPath, { force: true });
  await fsp.writeFile(testPage, "<!doctype html><html><body>packaged zero-state proof</body></html>\n");

  log(`launching ${appExe}`);
  const child = spawn(appExe, [], {
    cwd: path.dirname(appExe),
    env: {
      ...process.env,
      EDMG_STUDIO_HOME: studioHome,
      EDMG_STUDIO_BACKEND_HOST: "127.0.0.1",
      EDMG_STUDIO_BACKEND_PORT: String(port),
      EDMG_STUDIO_TEST_MODE: "1",
      EDMG_STUDIO_TEST_PAGE: testPage,
      EDMG_STUDIO_TEST_FAKE_PATH_ACTIONS: "1",
      EDMG_SETUP_IGNORE_SYSTEM_7Z: "1",
      EDMG_SETUP_IGNORE_SYSTEM_OLLAMA: "1",
      EDMG_AI_MODE: "local",
      EDMG_AI_PROVIDER: "ollama",
      EDMG_AI_OLLAMA_URL: ollamaUrl,
      EDMG_AI_OLLAMA_MODEL: requestedModel,
      ELECTRON_DISABLE_SECURITY_WARNINGS: "1",
    },
    stdio: "ignore",
  });

  try {
    const health = await waitForHealth(baseUrl);
    const initialStatus = await requestJson(`${baseUrl}/v1/setup/status`);
    const fullSetup = await postJson(`${baseUrl}/v1/setup/full/install`, {
      flavor: "cpu",
      model: requestedModel,
    });
    const taskId = fullSetup?.task?.id;
    assert.ok(taskId, `Full setup did not return a task id: ${JSON.stringify(fullSetup)}`);

    const { status: finalStatus, task } = await waitForTask(baseUrl, taskId);
    const config = await requestJson(`${baseUrl}/v1/config`);
    const summary = {
      ok: task?.status === "done",
      studioHome,
      baseUrl,
      health,
      task,
      requestedModel,
      ollamaUrl,
      initialStatus: {
        ollamaOk: initialStatus?.ollama?.ok ?? null,
        ollamaUrl: initialStatus?.ollama?.url ?? null,
        ollamaLaunchAvailable: initialStatus?.ollama?.launch_available ?? null,
        sevenZipOk: initialStatus?.sevenzip?.ok ?? null,
        sevenZipPath: initialStatus?.sevenzip?.path ?? null,
      },
      finalStatus: {
        ollamaOk: finalStatus?.ollama?.ok ?? null,
        ollamaUrl: finalStatus?.ollama?.url ?? null,
        modelPresent: finalStatus?.ollama?.model_present ?? null,
        ollamaExe: finalStatus?.ollama?.ollama_exe ?? null,
        ollamaManagedModelsDir: finalStatus?.ollama?.managed_models_dir ?? null,
        launchAvailable: finalStatus?.ollama?.launch_available ?? null,
        sevenZipOk: finalStatus?.sevenzip?.ok ?? null,
        sevenZipPath: finalStatus?.sevenzip?.path ?? null,
        comfyPortableInstalled: finalStatus?.comfyui?.portable_installed ?? null,
        backendBundleOk: finalStatus?.backend_bundle?.ok ?? null,
      },
      config: {
        studioHome: config?.studio_home ?? null,
        externalDir: config?.external_dir ?? null,
        modelsDir: config?.models_dir ?? null,
        ollamaModelsDir: config?.ollama_models_dir ?? null,
      },
      expected: {
        expectedOllamaExe,
        expectedSevenZip,
      },
      exists: {
        ollamaExe: fs.existsSync(expectedOllamaExe),
        sevenZipExe: fs.existsSync(expectedSevenZip),
      },
    };

    console.log(JSON.stringify(summary, null, 2));

    assert.equal(task?.status, "done", `Full setup task should succeed. Last log: ${task?.last_log || task?.error || "unknown"}`);
    assert.equal(summary.finalStatus.backendBundleOk, true, "Full setup should ensure the backend runtime bundle");
    assert.equal(summary.finalStatus.sevenZipOk, true, "Full setup should provision 7-Zip without using the system install");
    assert.equal(summary.finalStatus.ollamaOk, true, "Full setup should leave Ollama running");
    assert.equal(summary.finalStatus.ollamaUrl, ollamaUrl, "Ollama should be running on the Studio-managed proof port");
    assert.equal(summary.finalStatus.modelPresent, true, "Full setup should pull the requested Ollama model");
    assert.equal(summary.finalStatus.comfyPortableInstalled, true, "Full setup should install ComfyUI Portable");
    assert.equal(summary.config.studioHome, studioHome, "Packaged config should reflect the requested Studio home");
    assert.equal(summary.config.externalDir, externalDir, "External tools should stay under the chosen Studio home");
    assert.equal(summary.finalStatus.sevenZipPath, expectedSevenZip, "7-Zip should resolve to the Studio-managed portable copy");
    assert.equal(summary.finalStatus.ollamaExe, expectedOllamaExe, "Ollama should resolve to the Studio-managed install");
    assert.equal(summary.exists.ollamaExe, true, "Studio-managed Ollama executable should exist");
    assert.equal(summary.exists.sevenZipExe, true, "Studio-managed 7-Zip executable should exist");
  } finally {
    await killProcessTree(child);
    await stopProcessesByPathPrefix(path.join(studioHome, "external", "ollama"));
    await stopProcessesByPathPrefix(path.join(studioHome, "external", "ComfyUI_windows_portable"));
    await stopExistingPackagedProcesses();
    await restoreBootstrap(bootstrapPath, bootstrapBackup);
    if (!KEEP_PROOF_HOME) {
      try {
        await fsp.rm(studioHome, { recursive: true, force: true });
      } catch (error) {
        console.warn("[packaged-zero-state-setup] cleanup warning", error);
      }
    }
  }
}

main().catch((error) => {
  console.error("[packaged-zero-state-setup] FAILED", error);
  process.exit(1);
});
