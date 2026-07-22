import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";

export function createDirectorRuntime({
  app,
  rootDir,
  isWindows,
  directorHost,
  directorPort,
  directorPublicBaseUrl,
  directorReadyTimeoutMs,
  spawnDirector,
  pathExistsSync,
  ensureDirSync,
  safeStreamWrite,
  getStudioPaths,
  getBackendUrl,
  spawnProcess = spawn,
}) {
  const serviceUrl = `http://${directorHost}:${directorPort}`;
  let currentDirectorUrl = serviceUrl;
  let currentDirectorPublicBaseUrl = String(directorPublicBaseUrl || serviceUrl).trim() || serviceUrl;
  let directorProc = null;
  let lastError = "";
  let lastStartedAt = "";

  function getDirectorRootDir() {
    if (app.isPackaged) {
      return path.join(process.resourcesPath, "director");
    }
    return path.resolve(rootDir, "..", "..", "chatgpt-apps", "edmg-director");
  }

  function getDirectorServerEntrypoint() {
    return path.join(getDirectorRootDir(), "dist-server", "server.js");
  }

  function resolveDirectorLogPaths(logsDir) {
    const directorDir = path.join(logsDir || getStudioPaths().logsDir || app.getPath("logs"), "director");
    ensureDirSync(directorDir);
    return {
      stdoutPath: path.join(directorDir, "director-stdout.log"),
      stderrPath: path.join(directorDir, "director-stderr.log"),
    };
  }

  function terminateProcessTree(pid) {
    if (!pid) return;
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

  function appendChildOutput(stream, filePath) {
    if (!stream || !filePath) return null;
    ensureDirSync(path.dirname(filePath));
    let fileStream;
    try {
      fileStream = fs.createWriteStream(filePath, { flags: "a" });
    } catch (error) {
      console.warn("[director] failed to open log stream", { filePath, error });
      return null;
    }
    fileStream.on("error", (error) => {
      console.warn("[director] log stream error", { filePath, error });
    });
    stream.on("data", (chunk) => {
      safeStreamWrite(fileStream, chunk);
    });
    return fileStream;
  }

  function closeLogStream(stream) {
    if (!stream) return;
    try {
      stream.end();
    } catch {}
  }

  function getAdvertisedBaseUrl() {
    return String(currentDirectorPublicBaseUrl || serviceUrl).trim() || serviceUrl;
  }

  function buildDirectorChildEnv() {
    const env = {
      ...process.env,
      HOST: directorHost,
      PORT: String(directorPort),
      BASE_URL: getAdvertisedBaseUrl(),
      EDMG_BASE_URL: getBackendUrl(),
    };

    for (const key of [
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

  function getDirectorLaunchSpec() {
    const cwd = getDirectorRootDir();
    const entrypoint = getDirectorServerEntrypoint();
    if (app.isPackaged) {
      return {
        command: process.execPath,
        args: [entrypoint],
        cwd,
        env: {
          ELECTRON_RUN_AS_NODE: "1",
        },
        label: "packaged-director",
        requiredPaths: [entrypoint],
        buildSteps: [],
      };
    }

    return {
      command: process.execPath,
      args: [entrypoint],
      cwd,
      env: {
        ELECTRON_RUN_AS_NODE: "1",
      },
      label: "dev-director",
      requiredPaths: [entrypoint, path.join(cwd, "assets", "review-board.html")],
      buildSteps: [
        {
          label: "widget",
          scriptPath: path.join(cwd, "node_modules", "vite", "bin", "vite.js"),
          args: ["build"],
        },
        {
          label: "server",
          scriptPath: path.join(cwd, "node_modules", "typescript", "bin", "tsc"),
          args: ["-p", path.join(cwd, "tsconfig.server.json")],
        },
      ],
    };
  }

  function runDirectorBuildStep(step, childEnv, logPaths) {
    return new Promise((resolve) => {
      let settled = false;
      let child;
      try {
        child = spawnProcess(process.execPath, [step.scriptPath, ...step.args], {
          cwd: getDirectorRootDir(),
          env: {
            ...childEnv,
            ELECTRON_RUN_AS_NODE: "1",
          },
          shell: false,
          windowsHide: true,
          stdio: ["ignore", "pipe", "pipe"],
        });
      } catch (error) {
        lastError = `EDMG Director ${step.label} build could not start: ${String(error?.message ?? error)}`;
        resolve(false);
        return;
      }

      const stdoutLog = appendChildOutput(child.stdout, logPaths.stdoutPath);
      const stderrLog = appendChildOutput(child.stderr, logPaths.stderrPath);
      const finish = (ok, detail = "") => {
        if (settled) return;
        settled = true;
        closeLogStream(stdoutLog);
        closeLogStream(stderrLog);
        if (!ok) {
          lastError = detail || `EDMG Director ${step.label} build failed.`;
        }
        resolve(ok);
      };

      child.once("error", (error) => {
        finish(false, `EDMG Director ${step.label} build failed to start: ${String(error?.message ?? error)}`);
      });
      child.once("exit", (code, signal) => {
        if (code === 0) {
          finish(true);
          return;
        }
        const detail = signal ? ` after signal ${signal}` : ` with code ${code ?? "unknown"}`;
        finish(false, `EDMG Director ${step.label} build exited${detail}.`);
      });
    });
  }

  async function probeDirector(url = currentDirectorUrl) {
    return new Promise((resolve) => {
      const req = http.get(url, (res) => {
        let body = "";
        res.setEncoding("utf8");
        res.on("data", (chunk) => {
          body += chunk;
          if (body.length > 8192) {
            body = body.slice(0, 8192);
          }
        });
        res.on("end", () => {
          if (!res.statusCode || res.statusCode < 200 || res.statusCode >= 500) {
            resolve(false);
            return;
          }
          try {
            const payload = JSON.parse(body);
            resolve(payload?.ok === true && payload?.name === "edmg-director");
          } catch {
            resolve(false);
          }
        });
      });

      req.on("error", () => resolve(false));
      req.setTimeout(1500, () => {
        req.destroy();
        resolve(false);
      });
    });
  }

  function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function waitForDirectorReady(timeoutMs = directorReadyTimeoutMs) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (await probeDirector(serviceUrl)) {
        currentDirectorUrl = serviceUrl;
        return true;
      }
      await delay(300);
    }
    return false;
  }

  async function startDirectorIfNeeded() {
    if (!spawnDirector) {
      return false;
    }

    currentDirectorUrl = serviceUrl;
    if (await probeDirector(serviceUrl)) {
      lastError = "";
      return true;
    }

    if (directorProc?.pid) {
      return waitForDirectorReady();
    }

    const spec = getDirectorLaunchSpec();
    lastStartedAt = new Date().toISOString();
    const baseChildEnv = buildDirectorChildEnv();
    const logPaths = resolveDirectorLogPaths();

    for (const step of spec.buildSteps) {
      if (!pathExistsSync(step.scriptPath)) {
        lastError = `EDMG Director ${step.label} build tool is missing: ${step.scriptPath}`;
        console.warn("[director] build tool missing", lastError);
        return false;
      }
      if (!(await runDirectorBuildStep(step, baseChildEnv, logPaths))) {
        console.warn("[director] build failed", lastError);
        return false;
      }
    }

    const missingRuntimePath = spec.requiredPaths.find((requiredPath) => !pathExistsSync(requiredPath));
    if (missingRuntimePath) {
      lastError = `EDMG Director runtime is missing: ${missingRuntimePath}`;
      console.warn("[director] runtime missing", lastError);
      return false;
    }

    const childEnv = {
      ...baseChildEnv,
      ...spec.env,
    };
    const child = spawnProcess(spec.command, spec.args, {
      cwd: spec.cwd,
      env: childEnv,
      shell: spec.shell === true,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });

    const stdoutLog = appendChildOutput(child.stdout, logPaths.stdoutPath);
    const stderrLog = appendChildOutput(child.stderr, logPaths.stderrPath);

    child.on("error", (error) => {
      lastError = String(error?.message ?? error ?? "Unknown EDMG Director launch error");
      console.error("[director] failed to start", error);
    });
    child.on("exit", (code, signal) => {
      directorProc = null;
      closeLogStream(stdoutLog);
      closeLogStream(stderrLog);
      if (code !== 0 && code !== null) {
        lastError = `EDMG Director exited with code ${code}.`;
      } else if (signal) {
        lastError = `EDMG Director exited after signal ${signal}.`;
      }
    });

    directorProc = {
      pid: child.pid,
      child,
      kill() {
        terminateProcessTree(child.pid);
      },
    };

    const ready = await waitForDirectorReady();
    if (!ready) {
      lastError =
        lastError ||
        `EDMG Director did not become ready at ${serviceUrl} within ${directorReadyTimeoutMs} ms.`;
      console.warn("[director] startup timeout", {
        serviceUrl,
        publicBaseUrl: getAdvertisedBaseUrl(),
      });
    } else {
      lastError = "";
    }
    return ready;
  }

  function stopDirector() {
    if (!directorProc) return;
    directorProc.kill();
    directorProc = null;
  }

  async function restartDirector({ directorPublicBaseUrl: nextPublicBaseUrl } = {}) {
    currentDirectorPublicBaseUrl = String(nextPublicBaseUrl || serviceUrl).trim() || serviceUrl;
    stopDirector();
    currentDirectorUrl = serviceUrl;
    lastError = "";
    await delay(400);
    return startDirectorIfNeeded();
  }

  async function getDirectorStatus() {
    const reachable = await probeDirector(serviceUrl);
    return {
      ok: true,
      available: reachable,
      managed: spawnDirector,
      serviceUrl,
      mcpUrl: `${serviceUrl.replace(/\/+$/, "")}/mcp`,
      advertisedBaseUrl: getAdvertisedBaseUrl(),
      backendUrl: getBackendUrl(),
      pid: directorProc?.pid ?? null,
      lastError,
      startedAt: lastStartedAt || null,
      packaged: app.isPackaged,
    };
  }

  return {
    getCurrentDirectorUrl: () => currentDirectorUrl,
    getCurrentDirectorMcpUrl: () => `${currentDirectorUrl.replace(/\/+$/, "")}/mcp`,
    startDirectorIfNeeded,
    stopDirector,
    restartDirector,
    getDirectorStatus,
  };
}
