import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import path from "node:path";

export const SOURCE_RUNTIME_CAPABILITY_EXTRAS = Object.freeze([
  "core",
  "audio",
  "asr",
  "internal-video",
  "aws",
]);

const PACKAGED_BACKEND_LAUNCH_ATTEMPTS = 3;

export function normalizeAcceleratorProfile(value, { isWindows = process.platform === "win32" } = {}) {
  const aliases = { nvidia: "cuda", amd: "directml" };
  const requested = String(value || "cpu").trim().toLowerCase();
  const profile = aliases[requested] || requested;
  if (!new Set(["cpu", "directml", "cuda"]).has(profile)) {
    throw new Error(`Unsupported accelerator profile ${JSON.stringify(value)}; choose cpu, directml, or cuda.`);
  }
  if (profile === "directml" && !isWindows) {
    throw new Error("The directml accelerator profile is supported only on Windows.");
  }
  return profile;
}

export function buildBackendLaunchSpec({
  appIsPackaged,
  resourcesPath,
  rootDir,
  isWindows,
  backendHost,
  backendPort,
  env = process.env,
}) {
  if (appIsPackaged) {
    const pathApi = isWindows ? path.win32 : path;
    const exeName = isWindows ? "edmg-studio-backend.exe" : "edmg-studio-backend";
    const command = pathApi.join(resourcesPath, "backend", exeName);
    return {
      command,
      args: ["serve", "--host", backendHost, "--port", String(backendPort)],
      cwd: pathApi.dirname(command),
      label: "packaged-backend",
    };
  }

  const acceleratorProfile = normalizeAcceleratorProfile(
    env.EDMG_BACKEND_ACCELERATOR_PROFILE,
    { isWindows },
  );
  const command = String(env.EDMG_UV_BIN || "uv").trim() || "uv";
  const args = ["run", "--frozen", "--no-default-groups", "--python", "3.12"];
  for (const extra of [acceleratorProfile, ...SOURCE_RUNTIME_CAPABILITY_EXTRAS]) {
    args.push("--extra", extra);
  }
  args.push(
    "python",
    "-m",
    "edmg_studio_backend",
    "serve",
    "--host",
    backendHost,
    "--port",
    String(backendPort),
  );
  return {
    command,
    args,
    cwd: path.join(rootDir, "python_backend"),
    label: "uv-frozen-backend",
    acceleratorProfile,
  };
}

export function resolveStudioUiOrigin(devServerUrl, { isDev = true } = {}) {
  if (!isDev) {
    // Packaged Electron uses loadFile → browser Origin "null".
    return "null";
  }
  const raw = String(devServerUrl || "").trim();
  if (!raw) return "null";
  try {
    return new URL(raw).origin;
  } catch {
    return "null";
  }
}

export function executablePathsEqual(
  left,
  right,
  { isWindows = process.platform === "win32" } = {},
) {
  const leftValue = String(left || "").trim();
  const rightValue = String(right || "").trim();
  if (!leftValue || !rightValue) return false;

  const pathApi = isWindows ? path.win32 : path;
  const normalizedLeft = pathApi.resolve(leftValue);
  const normalizedRight = pathApi.resolve(rightValue);
  return isWindows
    ? normalizedLeft.toLowerCase() === normalizedRight.toLowerCase()
    : normalizedLeft === normalizedRight;
}

export function managedBackendUrl(host, port) {
  const rawHost = String(host || "127.0.0.1").trim() || "127.0.0.1";
  const publicHost = rawHost === "0.0.0.0"
    ? "127.0.0.1"
    : rawHost === "::"
      ? "::1"
      : rawHost;
  const urlHost = publicHost.includes(":") && !publicHost.startsWith("[")
    ? `[${publicHost}]`
    : publicHost;
  return `http://${urlHost}:${String(port)}`;
}

export function parseWindowsNetstatListeningPid(output, port) {
  const targetPort = Number(port);
  if (!Number.isFinite(targetPort) || targetPort <= 0) return null;

  for (const rawLine of String(output || "").split(/\r?\n/)) {
    const fields = rawLine.trim().split(/\s+/);
    if (fields.length < 5 || String(fields[0]).toUpperCase() !== "TCP") continue;
    const state = fields[3];
    const rawPid = fields[4];
    if (String(state).toUpperCase() !== "LISTENING") continue;
    const localAddress = String(fields[1] || "");
    const portMatch = /:(\d+)$/.exec(localAddress);
    if (!portMatch || Number(portMatch[1]) !== targetPort) continue;
    const pid = Number(rawPid);
    if (Number.isFinite(pid) && pid > 0) return pid;
  }
  return null;
}

export function createBackendRuntime({
  app,
  dialog,
  rootDir,
  isWindows,
  backendHost,
  backendPort,
  backendUrl,
  backendReadyTimeoutMs,
  testMode,
  pathExistsSync,
  ensureDirSync,
  safeStreamWrite,
  getStudioPaths,
  buildManagedStudioEnv,
  buildManagedAiEnv,
  isDev = !app?.isPackaged,
  devServerUrl = "",
  studioUiOrigin = "",
  resourcesPath = process.resourcesPath,
  runtimeOps = {},
}) {
  let activeBackendPort = Number(backendPort);
  let currentBackendUrl = backendUrl || managedBackendUrl(backendHost, activeBackendPort);
  let backendProc = null;
  const uiOrigin =
    String(studioUiOrigin || "").trim() || resolveStudioUiOrigin(devServerUrl, { isDev });

  function logBackendUrlMarker() {
    console.log(`EDMG_BACKEND_URL=${currentBackendUrl}`);
  }

  function getCurrentBackendUrl() {
    return currentBackendUrl;
  }

  function resolveManagedFfmpegPath() {
    const explicit = String(process.env.EDMG_FFMPEG_PATH ?? "").trim();
    if (explicit) {
      if (!path.isAbsolute(explicit) || pathExistsSync(explicit)) {
        return explicit;
      }
      console.warn("[ffmpeg] explicit EDMG_FFMPEG_PATH missing, falling back:", explicit);
    }

    const exeName = isWindows ? "ffmpeg.exe" : "ffmpeg";
    const candidates = app.isPackaged
      ? [
          path.join(resourcesPath, "bin", exeName),
          path.join(resourcesPath, "electron-resources", "bin", exeName),
        ]
      : [
          path.join(rootDir, "electron-resources", "bin", exeName),
        ];

    for (const candidate of candidates) {
      if (pathExistsSync(candidate)) {
        return candidate;
      }
    }

    return explicit || "ffmpeg";
  }

  function getBackendLaunchSpec() {
    return buildBackendLaunchSpec({
      appIsPackaged: app.isPackaged,
      resourcesPath,
      rootDir,
      isWindows,
      backendHost,
      backendPort: activeBackendPort,
    });
  }

  function buildBackendChildEnv(managedStudioEnv, ffmpegPath, spec) {
    const env = {
      ...process.env,
      ...managedStudioEnv,
      ...buildManagedAiEnv(),
      EDMG_STUDIO_BACKEND_HOST: backendHost,
      EDMG_STUDIO_BACKEND_PORT: String(activeBackendPort),
      EDMG_FFMPEG_PATH: ffmpegPath,
      MPLBACKEND: process.env.MPLBACKEND || "Agg",
    };
    if (spec.acceleratorProfile) {
      env.EDMG_BACKEND_ACCELERATOR_PROFILE = spec.acceleratorProfile;
      env.NVIDIA_TENSORRT_DISABLE_INTERNAL_PIP = "1";
    }

    for (const key of [
      "ELECTRON_RUN_AS_NODE",
      "ELECTRON_NO_ATTACH_CONSOLE",
      "ELECTRON_NO_ASAR",
      "ELECTRON_ENABLE_LOGGING",
      "CHROME_CRASHPAD_PIPE_NAME",
      "NODE_OPTIONS",
      "VITE_DEV_SERVER_URL",
      "EDMG_STUDIO_TEST_MODE",
      "EDMG_STUDIO_TEST_PAGE",
      "EDMG_STUDIO_TEST_REPORT_PATH",
      "EDMG_STUDIO_TEST_PROBE_REVEAL_PATH",
      "EDMG_STUDIO_TEST_PROBE_OPEN_PATH",
      "EDMG_STUDIO_TEST_EXPECT_BACKEND_URL",
      "EDMG_STUDIO_TEST_FAKE_PATH_ACTIONS",
    ]) {
      delete env[key];
    }

    return env;
  }

  function resolveBackendLogPaths(logsDir) {
    const backendDir = path.join(logsDir || getStudioPaths().logsDir || app.getPath("logs"), "backend");
    ensureDirSync(backendDir);
    return {
      stdoutPath: path.join(backendDir, "backend-stdout.log"),
      stderrPath: path.join(backendDir, "backend-stderr.log"),
    };
  }

  function tailFileSync(filePath, maxLines = 40) {
    if (!filePath || !pathExistsSync(filePath)) return "";
    try {
      const lines = fs.readFileSync(filePath, "utf8").split(/\r?\n/).filter(Boolean);
      return lines.slice(-maxLines).join("\n");
    } catch {
      return "";
    }
  }

  function terminateProcessTree(pid) {
    if (!pid) return;
    if (typeof runtimeOps.terminateProcessTree === "function") {
      runtimeOps.terminateProcessTree(pid);
      return;
    }
    if (isWindows) {
      const result = spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], {
        windowsHide: true,
        stdio: "ignore",
        shell: false,
      });
      if (result.status === 0) return;
    }
    try {
      process.kill(pid);
    } catch {}
  }

  function findListeningPid(port) {
    const target = Number(port);
    if (!Number.isFinite(target) || target <= 0) return null;
    if (typeof runtimeOps.findListeningPid === "function") {
      return runtimeOps.findListeningPid(target);
    }

    if (isWindows) {
      const result = spawnSync("netstat", ["-ano", "-p", "TCP"], {
        windowsHide: true,
        encoding: "utf8",
        shell: false,
      });
      if (result.status !== 0) return null;
      return parseWindowsNetstatListeningPid(result.stdout, target);
    }

    const result = spawnSync("lsof", ["-nP", `-iTCP:${target}`, "-sTCP:LISTEN", "-t"], {
      encoding: "utf8",
      shell: false,
    });
    if (result.status !== 0) return null;
    const pid = Number(String(result.stdout || "").trim().split(/\r?\n/)[0]);
    return Number.isFinite(pid) && pid > 0 ? pid : null;
  }

  function resolveProcessExecutablePath(pid) {
    const target = Number(pid);
    if (!Number.isFinite(target) || target <= 0) return "";
    if (typeof runtimeOps.resolveProcessExecutablePath === "function") {
      return String(runtimeOps.resolveProcessExecutablePath(target) || "").trim();
    }

    if (isWindows) {
      const result = spawnSync(
        "powershell",
        [
          "-NoProfile",
          "-NonInteractive",
          "-Command",
          `(Get-CimInstance Win32_Process -Filter \"ProcessId=${target}\" -ErrorAction SilentlyContinue).ExecutablePath`,
        ],
        {
          windowsHide: true,
          encoding: "utf8",
          shell: false,
        },
      );
      return result.status === 0 ? String(result.stdout || "").trim() : "";
    }

    if (process.platform === "linux") {
      try {
        return fs.readlinkSync(`/proc/${target}/exe`);
      } catch {
        return "";
      }
    }

    const result = spawnSync("ps", ["-p", String(target), "-o", "comm="], {
      encoding: "utf8",
      shell: false,
    });
    return result.status === 0 ? String(result.stdout || "").trim() : "";
  }

  function allocateAvailableBackendPort() {
    if (typeof runtimeOps.allocateAvailableBackendPort === "function") {
      return Promise.resolve(runtimeOps.allocateAvailableBackendPort(backendHost));
    }
    return new Promise((resolve, reject) => {
      const server = net.createServer();
      let settled = false;
      const finish = (error, port) => {
        if (settled) return;
        settled = true;
        if (error) reject(error);
        else resolve(port);
      };
      server.unref();
      server.once("error", (error) => finish(error));
      server.listen({ host: backendHost, port: 0, exclusive: true }, () => {
        const address = server.address();
        const port = typeof address === "object" && address ? Number(address.port) : 0;
        server.close((error) => {
          if (error) finish(error);
          else if (!Number.isFinite(port) || port <= 0) finish(new Error("Could not allocate a local backend port."));
          else finish(null, port);
        });
      });
    });
  }

  async function movePackagedBackendToAvailablePort(reason) {
    const previousUrl = currentBackendUrl;
    try {
      activeBackendPort = await allocateAvailableBackendPort();
    } catch (error) {
      const message = `Could not allocate a private local port for the packaged backend: ${error?.message ?? error}`;
      console.error("[backend]", message);
      if (!testMode) dialog.showErrorBox("EDMG Studio backend port conflict", message);
      return false;
    }
    currentBackendUrl = managedBackendUrl(backendHost, activeBackendPort);
    console.warn(
      `[backend] ${reason}; leaving ${previousUrl} untouched and using ${currentBackendUrl} for this Studio session`,
    );
    logBackendUrlMarker();
    return true;
  }

  function inspectPackagedBackendPortOwner() {
    if (!app.isPackaged) return { state: "not-packaged" };
    const listenerPid = findListeningPid(activeBackendPort);
    if (!listenerPid) return { state: "vacant" };
    const expectedExecutable = getBackendLaunchSpec().command;
    const listenerExecutable = resolveProcessExecutablePath(listenerPid);
    return {
      state: executablePathsEqual(listenerExecutable, expectedExecutable, { isWindows })
        ? "packaged"
        : "foreign",
      listenerPid,
      listenerExecutable,
      expectedExecutable,
    };
  }

  async function reclaimStaleBackendPort(reason) {
    const pid = findListeningPid(activeBackendPort);
    if (!pid) {
      console.warn(`[backend] ${reason}; port ${activeBackendPort} has no listener to reclaim`);
      return false;
    }

    console.warn(
      `[backend] ${reason}; terminating PID ${pid} on :${activeBackendPort} so Desktop can spawn a fresh backend`,
    );
    terminateProcessTree(pid);

    const deadline = Date.now() + 5000;
    while (Date.now() < deadline) {
      if (!(await probeBackend())) return true;
      await delay(200);
    }

    return !(await probeBackend());
  }

  function quotePowerShell(value) {
    return `'${String(value ?? "").replace(/'/g, "''")}'`;
  }

  function launchPackagedBackendWindows(spec, env, logPaths) {
    if (typeof runtimeOps.launchPackagedBackendWindows === "function") {
      return Promise.resolve(runtimeOps.launchPackagedBackendWindows(spec, env, logPaths));
    }
    const argList = (spec.args || []).map((arg) => quotePowerShell(String(arg))).join(", ");
    const stdoutPath = logPaths?.stdoutPath || "";
    const stderrPath = logPaths?.stderrPath || "";
    if (stdoutPath) ensureDirSync(path.dirname(stdoutPath));
    if (stderrPath) ensureDirSync(path.dirname(stderrPath));
    const script = [
      `$proc = Start-Process -FilePath ${quotePowerShell(spec.command)} -ArgumentList @(${argList}) -WorkingDirectory ${quotePowerShell(spec.cwd || path.dirname(spec.command))} -WindowStyle Hidden -RedirectStandardOutput ${quotePowerShell(stdoutPath)} -RedirectStandardError ${quotePowerShell(stderrPath)} -PassThru`,
      "[Console]::Out.Write($proc.Id)",
    ].filter(Boolean).join("; ");

    return new Promise((resolve, reject) => {
      const launcher = spawn("powershell", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], {
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
        shell: false,
        env,
      });
      let stdout = "";
      let stderr = "";

      launcher.stdout?.on("data", (chunk) => {
        stdout += String(chunk || "");
      });
      launcher.stderr?.on("data", (chunk) => {
        stderr += String(chunk || "");
      });
      launcher.on("error", (error) => {
        reject(error);
      });
      launcher.on("exit", (code) => {
        if (code !== 0) {
          reject(new Error(String(stderr || stdout || `PowerShell Start-Process failed with code ${code ?? "unknown"}`).trim()));
          return;
        }
        const pid = Number(String(stdout || "").trim());
        if (!Number.isFinite(pid) || pid <= 0) {
          reject(new Error(`Could not resolve packaged backend pid from Start-Process output: ${String(stdout || "").trim()}`));
          return;
        }
        resolve({
          pid,
          kind: "windows_start_process",
          expectedExecutable: spec.command,
          logPaths,
          kill() {
            terminateProcessTree(pid);
          },
        });
      });
    });
  }

  function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function probeBackend(url = currentBackendUrl) {
    if (typeof runtimeOps.probeBackend === "function") {
      return Boolean(await runtimeOps.probeBackend(url));
    }
    return new Promise((resolve) => {
      const req = http.get(`${url}/health`, (res) => {
        res.resume();
        resolve(res.statusCode != null && res.statusCode >= 200 && res.statusCode < 500);
      });

      req.on("error", () => resolve(false));
      req.setTimeout(1500, () => {
        req.destroy();
        resolve(false);
      });
    });
  }

  async function probeBackendAllowsStudioOrigin(url = currentBackendUrl) {
    if (typeof runtimeOps.probeBackendAllowsStudioOrigin === "function") {
      return Boolean(await runtimeOps.probeBackendAllowsStudioOrigin(url, uiOrigin));
    }
    const origin = uiOrigin || "null";
    return new Promise((resolve) => {
      const req = http.get(`${url}/health`, { headers: { Origin: origin } }, (res) => {
        const allow = String(res.headers["access-control-allow-origin"] || "").trim();
        res.resume();
        resolve(allow === "*" || allow === origin);
      });

      req.on("error", () => resolve(false));
      req.setTimeout(1500, () => {
        req.destroy();
        resolve(false);
      });
    });
  }

  async function waitForBackendReady(timeoutMs = backendReadyTimeoutMs) {
    const started = Date.now();

    while (Date.now() - started < timeoutMs) {
      if ((await probeBackend()) && (await probeBackendAllowsStudioOrigin())) {
        return true;
      }
      await delay(300);
    }

    return false;
  }

  async function retryPackagedBackendAfterOwnershipFailure(owner, launchAttempt) {
    const ownerDetail = owner.listenerExecutable
      ? `PID ${owner.listenerPid} (${owner.listenerExecutable})`
      : owner.listenerPid
        ? `PID ${owner.listenerPid} of unknown origin`
        : "an unverifiable listener";
    const reason = `${ownerDetail} claimed ${currentBackendUrl} while the bundled backend was starting`;
    stopBackend();

    if (launchAttempt + 1 >= PACKAGED_BACKEND_LAUNCH_ATTEMPTS) {
      const message =
        `${reason}. Studio stopped after ${PACKAGED_BACKEND_LAUNCH_ATTEMPTS} safe launch attempts ` +
        "instead of attaching to an unverified process.";
      console.error("[backend]", message);
      if (!testMode) dialog.showErrorBox("EDMG Studio backend port conflict", message);
      return false;
    }

    if (!(await movePackagedBackendToAvailablePort(reason))) return false;
    return startBackendIfNeeded(launchAttempt + 1);
  }

  async function startBackendIfNeeded(launchAttempt = 0) {
    logBackendUrlMarker();
    if ((process.env.EDMG_STUDIO_SPAWN_BACKEND ?? "1") === "0") {
      console.log("[edmg] spawn backend=false");
      return false;
    }

    if (app.isPackaged) {
      const owner = inspectPackagedBackendPortOwner();
      if (owner.state === "foreign") {
        const detail = owner.listenerExecutable
          ? `PID ${owner.listenerPid} (${owner.listenerExecutable}) owns port ${activeBackendPort}`
          : `PID ${owner.listenerPid} of unknown origin owns port ${activeBackendPort}`;
        if (!(await movePackagedBackendToAvailablePort(detail))) return false;
      } else if (owner.state === "packaged") {
        console.log(
          `[backend] packaged backend PID ${owner.listenerPid} already owns port ${activeBackendPort}; waiting for readiness`,
        );
        const ready = await waitForBackendReady();
        const verifiedOwner = ready ? inspectPackagedBackendPortOwner() : null;
        if (ready && verifiedOwner?.state === "packaged") {
          logBackendUrlMarker();
          return true;
        }
        const reason = ready
          ? `listener ownership changed while checking packaged backend PID ${owner.listenerPid} on port ${activeBackendPort}`
          : `packaged backend PID ${owner.listenerPid} on port ${activeBackendPort} did not become ready`;
        if (!(await movePackagedBackendToAvailablePort(
          reason,
        ))) return false;
      }
    }

    if (await probeBackend()) {
      if (app.isPackaged) {
        const owner = inspectPackagedBackendPortOwner();
        if (owner.state !== "packaged") {
          const detail = owner.listenerExecutable
            ? `listener ${owner.listenerExecutable} is not the bundled backend`
            : "listener ownership could not be verified";
          if (!(await movePackagedBackendToAvailablePort(detail))) return false;
        }
      }

      // A packaged listener mismatch moves currentBackendUrl, so only attach
      // when the newly selected URL is itself reachable.
      if (!(await probeBackend())) {
        // Fall through and launch the bundled backend on the selected port.
      } else if (await probeBackendAllowsStudioOrigin()) {
        const verifiedOwner = app.isPackaged ? inspectPackagedBackendPortOwner() : null;
        if (!app.isPackaged || verifiedOwner?.state === "packaged") {
          console.log("[backend] already reachable:", currentBackendUrl);
          logBackendUrlMarker();
          return true;
        }
        const detail = verifiedOwner?.listenerExecutable
          ? `listener ownership changed to ${verifiedOwner.listenerExecutable}`
          : "listener ownership changed and could not be verified";
        if (!(await movePackagedBackendToAvailablePort(detail))) return false;
      } else {
        // Desktop cannot use a backend that rejects the Studio UI Origin.
        // Reclaim the port and fall through to spawn instead of blocking the UI.
        const reclaimed = await reclaimStaleBackendPort(
          `${currentBackendUrl} answers /health but does not allow Origin ${uiOrigin} (CORS)`,
        );
        if (!reclaimed) {
          const message =
            `${currentBackendUrl} answers /health but does not allow Origin ${uiOrigin} (CORS),\n` +
            `and Studio could not free port ${activeBackendPort} automatically.\n\n` +
            "1. In the launcher, click Stop Backend\n" +
            `2. Or run: netstat -ano | findstr :${activeBackendPort}  then  taskkill /PID <pid> /F\n` +
            "3. Start Studio again so a fresh backend is spawned";
          console.warn("[backend] refusing attach (missing Studio UI CORS):\n" + message);
          if (!testMode) {
            dialog.showErrorBox("Stale Studio backend (CORS)", message);
          }
          return false;
        }
      }
    }

    const spec = getBackendLaunchSpec();
    const managedStudioEnv = buildManagedStudioEnv();
    const backendDataDir = managedStudioEnv.EDMG_STUDIO_DATA_DIR;
    const ffmpegPath = resolveManagedFfmpegPath();
    const childEnv = buildBackendChildEnv(managedStudioEnv, ffmpegPath, spec);
    const logPaths = resolveBackendLogPaths(managedStudioEnv.EDMG_STUDIO_LOGS_DIR);

    if (app.isPackaged && !pathExistsSync(spec.command)) {
      console.error("[backend] packaged backend missing:", spec.command);

      if (!testMode) {
        dialog.showErrorBox(
          "EDMG Studio backend missing",
          `Could not find packaged backend:\n${spec.command}`
        );
      }

      return false;
    }

    console.log("[edmg] spawn backend=true");
    console.log("[backend] launching", {
      label: spec.label,
      command: spec.command,
      args: spec.args,
      cwd: spec.cwd,
    });
    console.log("[backend] EDMG_STUDIO_DATA_DIR=", backendDataDir);
    console.log("[backend] EDMG_STUDIO_MODELS_DIR=", managedStudioEnv.EDMG_STUDIO_MODELS_DIR);
    console.log("[backend] EDMG_STUDIO_EXTERNAL_DIR=", managedStudioEnv.EDMG_STUDIO_EXTERNAL_DIR);
    console.log("[backend] OLLAMA_MODELS=", managedStudioEnv.OLLAMA_MODELS);
    console.log("[backend] EDMG_FFMPEG_PATH=", ffmpegPath);
    console.log("[backend] log files=", logPaths);

    try {
      if (app.isPackaged && isWindows) {
        backendProc = await launchPackagedBackendWindows(spec, childEnv, logPaths);
        console.log("[backend] launched via Start-Process", { pid: backendProc.pid });
      } else {
        backendProc = spawn(spec.command, spec.args, {
          cwd: spec.cwd,
          windowsHide: true,
          stdio: ["ignore", "pipe", "pipe"],
          env: childEnv,
        });
      }
    } catch (error) {
      console.error("[backend] spawn threw:", error);

      if (!testMode) {
        dialog.showErrorBox(
          "EDMG Studio backend failed to start",
          String(error?.message ?? error)
        );
      }

      return false;
    }

    if (typeof backendProc?.stdout?.on === "function") {
      backendProc.stdout.on("data", (chunk) => {
        safeStreamWrite(process.stdout, `[backend] ${chunk}`);
      });
    }

    if (typeof backendProc?.stderr?.on === "function") {
      backendProc.stderr.on("data", (chunk) => {
        safeStreamWrite(process.stderr, `[backend] ${chunk}`);
      });
    }

    if (typeof backendProc?.on === "function") {
      backendProc.on("error", (error) => {
        console.error("[backend] child process error:", error);

        if (!testMode) {
          dialog.showErrorBox(
            "EDMG Studio backend failed to start",
            `${error?.message ?? error}`
          );
        }
      });

      backendProc.on("exit", (code, signal) => {
        console.log("[backend] exited", { code, signal });
        backendProc = null;
      });
    }

    const ready = await waitForBackendReady();
    if (app.isPackaged) {
      const owner = inspectPackagedBackendPortOwner();
      if (owner.state !== "packaged") {
        return retryPackagedBackendAfterOwnershipFailure(owner, launchAttempt);
      }
    }
    if (!ready) {
      console.warn("[backend] not reachable:", currentBackendUrl);
      const stdoutTail = tailFileSync(logPaths.stdoutPath);
      const stderrTail = tailFileSync(logPaths.stderrPath);
      if (stdoutTail) console.warn("[backend] stdout tail:\n" + stdoutTail);
      if (stderrTail) console.warn("[backend] stderr tail:\n" + stderrTail);
    } else {
      logBackendUrlMarker();
    }

    return ready;
  }

  function stopBackend() {
    if (!backendProc) return;

    try {
      if (isWindows && backendProc.pid) {
        // uv and PyInstaller both create child processes on Windows. Killing
        // only the immediate child leaves Python serving on the managed port.
        if (backendProc.kind === "windows_start_process") {
          const actualExecutable = resolveProcessExecutablePath(backendProc.pid);
          if (executablePathsEqual(actualExecutable, backendProc.expectedExecutable, { isWindows })) {
            terminateProcessTree(backendProc.pid);
          } else {
            console.warn(
              `[backend] refusing to terminate stale PID ${backendProc.pid}; ` +
              `expected ${backendProc.expectedExecutable || "packaged backend"}, got ${actualExecutable || "no process"}`,
            );
          }
        } else {
          terminateProcessTree(backendProc.pid);
        }
      } else if (typeof backendProc.kill === "function") {
        backendProc.kill();
      } else if (backendProc.pid) {
        terminateProcessTree(backendProc.pid);
      }
    } catch (error) {
      console.warn("[backend] failed to stop cleanly:", error);
    }

    backendProc = null;
  }

  return {
    getCurrentBackendUrl,
    startBackendIfNeeded,
    stopBackend,
  };
}
