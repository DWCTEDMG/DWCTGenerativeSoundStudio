import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";

import {
  SOURCE_RUNTIME_CAPABILITY_EXTRAS,
  buildBackendLaunchSpec,
  createBackendRuntime,
  executablePathsEqual,
  managedBackendUrl,
  normalizeAcceleratorProfile,
  parseWindowsNetstatListeningPid,
  resolveStudioUiOrigin,
} from "./backend-runtime.mjs";
import { buildCacheEnvPaths } from "./storage-env.mjs";

const base = {
  resourcesPath: "C:\\Program Files\\EDMG Studio\\resources",
  rootDir: "C:\\src\\studio\\edmg-studio",
  isWindows: true,
  backendHost: "127.0.0.1",
  backendPort: 7863,
};

test("selected Studio cache overrides hostile inherited Hugging Face cache paths", () => {
  const selectedCacheRoot = path.resolve("selected-studio-cache");
  const hostileInheritedEnv = {
    HF_HOME: "G:\\stale\\huggingface",
    HF_HUB_CACHE: "G:\\stale\\huggingface\\hub",
    HF_XET_CACHE: "G:\\stale\\huggingface\\xet",
    HF_ASSETS_CACHE: "G:\\stale\\huggingface\\assets",
    HUGGINGFACE_HUB_CACHE: "G:\\legacy\\hub",
    HUGGINGFACE_ASSETS_CACHE: "G:\\legacy\\assets",
    TRANSFORMERS_CACHE: "G:\\stale\\transformers",
  };

  const launchEnv = {
    ...hostileInheritedEnv,
    ...buildCacheEnvPaths(selectedCacheRoot),
  };
  const huggingFaceRoot = path.join(selectedCacheRoot, "huggingface");

  assert.deepEqual(
    Object.fromEntries(Object.keys(hostileInheritedEnv).map((key) => [key, launchEnv[key]])),
    {
      HF_HOME: huggingFaceRoot,
      HF_HUB_CACHE: path.join(huggingFaceRoot, "hub"),
      HF_XET_CACHE: path.join(huggingFaceRoot, "xet"),
      HF_ASSETS_CACHE: path.join(huggingFaceRoot, "assets"),
      HUGGINGFACE_HUB_CACHE: path.join(huggingFaceRoot, "hub"),
      HUGGINGFACE_ASSETS_CACHE: path.join(huggingFaceRoot, "assets"),
      TRANSFORMERS_CACHE: path.join(selectedCacheRoot, "transformers"),
    },
  );
});

test("source backend runs exactly one profile through the frozen uv project", () => {
  const spec = buildBackendLaunchSpec({
    ...base,
    appIsPackaged: false,
    env: {
      EDMG_UV_BIN: "C:\\toolchain\\uv.exe",
      EDMG_BACKEND_ACCELERATOR_PROFILE: "cuda",
    },
  });

  assert.equal(spec.command, "C:\\toolchain\\uv.exe");
  assert.equal(spec.label, "uv-frozen-backend");
  assert.equal(spec.acceleratorProfile, "cuda");
  assert.deepEqual(spec.args.slice(0, 6), [
    "run",
    "--frozen",
    "--no-default-groups",
    "--python",
    "3.12",
    "--extra",
  ]);

  const extras = spec.args.flatMap((value, index) => value === "--extra" ? [spec.args[index + 1]] : []);
  assert.deepEqual(extras, ["cuda", ...SOURCE_RUNTIME_CAPABILITY_EXTRAS]);
  assert.equal(extras.filter((extra) => ["cpu", "directml", "cuda"].includes(extra)).length, 1);
  assert.deepEqual(spec.args.slice(-8), [
    "python",
    "-m",
    "edmg_studio_backend",
    "serve",
    "--host",
    "127.0.0.1",
    "--port",
    "7863",
  ]);
});

test("packaged backend ignores source Python and uv configuration", () => {
  const spec = buildBackendLaunchSpec({
    ...base,
    appIsPackaged: true,
    env: {
      EDMG_UV_BIN: "Z:\\missing\\uv.exe",
      EDMG_STUDIO_BACKEND_PYTHON: "Z:\\missing\\python.exe",
      EDMG_BACKEND_ACCELERATOR_PROFILE: "not-a-profile",
    },
  });

  assert.equal(spec.label, "packaged-backend");
  assert.match(spec.command, /resources[\\/]backend[\\/]edmg-studio-backend\.exe$/);
  assert.deepEqual(spec.args, ["serve", "--host", "127.0.0.1", "--port", "7863"]);
  assert.equal(spec.args.includes("uv"), false);
  assert.equal(spec.args.includes("python"), false);
});

test("packaged backend ownership compares resolved executable paths", () => {
  const installed = "G:\\Users\\lanak\\AppData\\Local\\Programs\\EDMG Studio\\resources\\backend\\edmg-studio-backend.exe";
  assert.equal(executablePathsEqual(installed.toUpperCase(), installed, { isWindows: true }), true);
  assert.equal(
    executablePathsEqual(
      "E:\\src\\python_backend\\.venv\\Scripts\\python.exe",
      installed,
      { isWindows: true },
    ),
    false,
  );
  assert.equal(executablePathsEqual("", installed, { isWindows: true }), false);
});

test("managed backend URLs support dynamic ports and wildcard bind hosts", () => {
  assert.equal(managedBackendUrl("127.0.0.1", 17863), "http://127.0.0.1:17863");
  assert.equal(managedBackendUrl("0.0.0.0", 7863), "http://127.0.0.1:7863");
  assert.equal(managedBackendUrl("::1", 7863), "http://[::1]:7863");
  assert.equal(managedBackendUrl("::", 7863), "http://[::1]:7863");
});

test("Windows netstat parsing finds IPv4 and IPv6 listeners with foreign-address columns", () => {
  const output = [
    "  Proto  Local Address          Foreign Address        State           PID",
    "  TCP    127.0.0.1:7863        0.0.0.0:0              LISTENING       18556",
    "  TCP    127.0.0.1:7864        127.0.0.1:50000        ESTABLISHED     42",
    "  TCP    [::1]:17863           [::]:0                 LISTENING       9568",
  ].join("\r\n");

  assert.equal(parseWindowsNetstatListeningPid(output, 7863), 18556);
  assert.equal(parseWindowsNetstatListeningPid(output, 17863), 9568);
  assert.equal(parseWindowsNetstatListeningPid(output, 7864), null);
  assert.equal(parseWindowsNetstatListeningPid(output, "invalid"), null);
});

test("packaged runtime preserves a foreign listener and launches on a private dynamic port", async () => {
  const previousSpawnSetting = process.env.EDMG_STUDIO_SPAWN_BACKEND;
  const previousFfmpegPath = process.env.EDMG_FFMPEG_PATH;
  process.env.EDMG_STUDIO_SPAWN_BACKEND = "1";
  process.env.EDMG_FFMPEG_PATH = "ffmpeg";

  const resourcesPath = "G:\\Apps\\EDMG Studio\\resources";
  const expectedExecutable = `${resourcesPath}\\backend\\edmg-studio-backend.exe`;
  let launched = false;
  let launchSpec = null;
  let launchEnvironment = null;
  const terminated = [];

  try {
    const runtime = createBackendRuntime({
      app: {
        isPackaged: true,
        getPath: () => "G:\\EDMG-Test-Home\\logs",
      },
      dialog: { showErrorBox: () => assert.fail("unexpected error dialog") },
      rootDir: "E:\\src\\studio\\edmg-studio",
      resourcesPath,
      isWindows: true,
      backendHost: "127.0.0.1",
      backendPort: 7863,
      backendUrl: "http://127.0.0.1:7863",
      backendReadyTimeoutMs: 50,
      testMode: true,
      pathExistsSync: () => true,
      ensureDirSync: () => {},
      safeStreamWrite: () => {},
      getStudioPaths: () => ({ logsDir: "G:\\EDMG-Test-Home\\logs" }),
      buildManagedStudioEnv: () => ({
        EDMG_STUDIO_DATA_DIR: "G:\\EDMG-Test-Home\\data",
        EDMG_STUDIO_MODELS_DIR: "G:\\EDMG-Test-Home\\models",
        EDMG_STUDIO_EXTERNAL_DIR: "G:\\EDMG-Test-Home\\external",
        EDMG_STUDIO_LOGS_DIR: "G:\\EDMG-Test-Home\\logs",
        OLLAMA_MODELS: "G:\\EDMG-Test-Home\\models\\ollama",
      }),
      buildManagedAiEnv: () => ({}),
      isDev: false,
      runtimeOps: {
        findListeningPid: (port) => {
          if (port === 7863) return 4242;
          if (port === 17863 && launched) return 9001;
          return null;
        },
        resolveProcessExecutablePath: (pid) => (
          pid === 4242 ? "E:\\src\\python_backend\\.venv\\Scripts\\python.exe" : expectedExecutable
        ),
        allocateAvailableBackendPort: () => 17863,
        probeBackend: (url) => launched && url === "http://127.0.0.1:17863",
        probeBackendAllowsStudioOrigin: () => true,
        launchPackagedBackendWindows: (spec, env) => {
          launched = true;
          launchSpec = spec;
          launchEnvironment = env;
          return {
            pid: 9001,
            kind: "windows_start_process",
            expectedExecutable: spec.command,
          };
        },
        terminateProcessTree: (pid) => terminated.push(pid),
      },
    });

    assert.equal(await runtime.startBackendIfNeeded(), true);
    assert.equal(runtime.getCurrentBackendUrl(), "http://127.0.0.1:17863");
    assert.equal(launchSpec.command, expectedExecutable);
    assert.deepEqual(launchSpec.args.slice(-2), ["--port", "17863"]);
    assert.equal(launchEnvironment.EDMG_STUDIO_BACKEND_PORT, "17863");
    assert.deepEqual(terminated, []);

    runtime.stopBackend();
    assert.deepEqual(terminated, [9001]);
  } finally {
    if (previousSpawnSetting === undefined) delete process.env.EDMG_STUDIO_SPAWN_BACKEND;
    else process.env.EDMG_STUDIO_SPAWN_BACKEND = previousSpawnSetting;
    if (previousFfmpegPath === undefined) delete process.env.EDMG_FFMPEG_PATH;
    else process.env.EDMG_FFMPEG_PATH = previousFfmpegPath;
  }
});

test("packaged runtime retries when a foreign process takes the selected port during launch", async () => {
  const previousSpawnSetting = process.env.EDMG_STUDIO_SPAWN_BACKEND;
  const previousFfmpegPath = process.env.EDMG_FFMPEG_PATH;
  process.env.EDMG_STUDIO_SPAWN_BACKEND = "1";
  process.env.EDMG_FFMPEG_PATH = "ffmpeg";

  const resourcesPath = "G:\\Apps\\EDMG Studio\\resources";
  const expectedExecutable = `${resourcesPath}\\backend\\edmg-studio-backend.exe`;
  const availablePorts = [17863, 17864];
  let launchCount = 0;
  const terminated = [];

  try {
    const runtime = createBackendRuntime({
      app: {
        isPackaged: true,
        getPath: () => "G:\\EDMG-Test-Home\\logs",
      },
      dialog: { showErrorBox: () => assert.fail("unexpected error dialog") },
      rootDir: "E:\\src\\studio\\edmg-studio",
      resourcesPath,
      isWindows: true,
      backendHost: "127.0.0.1",
      backendPort: 7863,
      backendUrl: "http://127.0.0.1:7863",
      backendReadyTimeoutMs: 50,
      testMode: true,
      pathExistsSync: () => true,
      ensureDirSync: () => {},
      safeStreamWrite: () => {},
      getStudioPaths: () => ({ logsDir: "G:\\EDMG-Test-Home\\logs" }),
      buildManagedStudioEnv: () => ({
        EDMG_STUDIO_DATA_DIR: "G:\\EDMG-Test-Home\\data",
        EDMG_STUDIO_MODELS_DIR: "G:\\EDMG-Test-Home\\models",
        EDMG_STUDIO_EXTERNAL_DIR: "G:\\EDMG-Test-Home\\external",
        EDMG_STUDIO_LOGS_DIR: "G:\\EDMG-Test-Home\\logs",
        OLLAMA_MODELS: "G:\\EDMG-Test-Home\\models\\ollama",
      }),
      buildManagedAiEnv: () => ({}),
      isDev: false,
      runtimeOps: {
        findListeningPid: (port) => {
          if (port === 7863) return 4242;
          if (port === 17863 && launchCount >= 1) return 4343;
          if (port === 17864 && launchCount >= 2) return 9002;
          return null;
        },
        resolveProcessExecutablePath: (pid) => (
          pid === 4242 || pid === 4343
            ? "E:\\src\\python_backend\\.venv\\Scripts\\python.exe"
            : expectedExecutable
        ),
        allocateAvailableBackendPort: () => availablePorts.shift(),
        probeBackend: (url) => (
          (url === "http://127.0.0.1:17863" && launchCount >= 1) ||
          (url === "http://127.0.0.1:17864" && launchCount >= 2)
        ),
        probeBackendAllowsStudioOrigin: () => true,
        launchPackagedBackendWindows: (spec) => {
          launchCount += 1;
          return {
            pid: 9000 + launchCount,
            kind: "windows_start_process",
            expectedExecutable: spec.command,
          };
        },
        terminateProcessTree: (pid) => terminated.push(pid),
      },
    });

    assert.equal(await runtime.startBackendIfNeeded(), true);
    assert.equal(launchCount, 2);
    assert.equal(runtime.getCurrentBackendUrl(), "http://127.0.0.1:17864");
    assert.deepEqual(terminated, [9001]);

    runtime.stopBackend();
    assert.deepEqual(terminated, [9001, 9002]);
  } finally {
    if (previousSpawnSetting === undefined) delete process.env.EDMG_STUDIO_SPAWN_BACKEND;
    else process.env.EDMG_STUDIO_SPAWN_BACKEND = previousSpawnSetting;
    if (previousFfmpegPath === undefined) delete process.env.EDMG_FFMPEG_PATH;
    else process.env.EDMG_FFMPEG_PATH = previousFfmpegPath;
  }
});

test("packaged runtime rechecks ownership immediately before attaching", async () => {
  const previousSpawnSetting = process.env.EDMG_STUDIO_SPAWN_BACKEND;
  const previousFfmpegPath = process.env.EDMG_FFMPEG_PATH;
  process.env.EDMG_STUDIO_SPAWN_BACKEND = "1";
  process.env.EDMG_FFMPEG_PATH = "ffmpeg";

  const resourcesPath = "G:\\Apps\\EDMG Studio\\resources";
  const expectedExecutable = `${resourcesPath}\\backend\\edmg-studio-backend.exe`;

  try {
    for (const preExistingPackagedListener of [true, false]) {
      let configuredPortInspections = 0;
      let launched = false;
      const terminated = [];
      const runtime = createBackendRuntime({
        app: {
          isPackaged: true,
          getPath: () => "G:\\EDMG-Test-Home\\logs",
        },
        dialog: { showErrorBox: () => assert.fail("unexpected error dialog") },
        rootDir: "E:\\src\\studio\\edmg-studio",
        resourcesPath,
        isWindows: true,
        backendHost: "127.0.0.1",
        backendPort: 7863,
        backendUrl: "http://127.0.0.1:7863",
        backendReadyTimeoutMs: 50,
        testMode: true,
        pathExistsSync: () => true,
        ensureDirSync: () => {},
        safeStreamWrite: () => {},
        getStudioPaths: () => ({ logsDir: "G:\\EDMG-Test-Home\\logs" }),
        buildManagedStudioEnv: () => ({
          EDMG_STUDIO_DATA_DIR: "G:\\EDMG-Test-Home\\data",
          EDMG_STUDIO_MODELS_DIR: "G:\\EDMG-Test-Home\\models",
          EDMG_STUDIO_EXTERNAL_DIR: "G:\\EDMG-Test-Home\\external",
          EDMG_STUDIO_LOGS_DIR: "G:\\EDMG-Test-Home\\logs",
          OLLAMA_MODELS: "G:\\EDMG-Test-Home\\models\\ollama",
        }),
        buildManagedAiEnv: () => ({}),
        isDev: false,
        runtimeOps: {
          findListeningPid: (port) => {
            if (port === 17863) return launched ? 9001 : null;
            if (port !== 7863) return null;
            configuredPortInspections += 1;
            if (preExistingPackagedListener) {
              return configuredPortInspections === 1 ? 5000 : 6000;
            }
            if (configuredPortInspections === 1) return null;
            return configuredPortInspections === 2 ? 5000 : 6000;
          },
          resolveProcessExecutablePath: (pid) => (
            pid === 6000
              ? "E:\\src\\python_backend\\.venv\\Scripts\\python.exe"
              : expectedExecutable
          ),
          allocateAvailableBackendPort: () => 17863,
          probeBackend: (url) => (
            url === "http://127.0.0.1:7863" ||
            (url === "http://127.0.0.1:17863" && launched)
          ),
          probeBackendAllowsStudioOrigin: () => true,
          launchPackagedBackendWindows: (spec) => {
            launched = true;
            return {
              pid: 9001,
              kind: "windows_start_process",
              expectedExecutable: spec.command,
            };
          },
          terminateProcessTree: (pid) => terminated.push(pid),
        },
      });

      assert.equal(await runtime.startBackendIfNeeded(), true);
      assert.equal(runtime.getCurrentBackendUrl(), "http://127.0.0.1:17863");
      assert.equal(launched, true);
      assert.deepEqual(terminated, []);
      runtime.stopBackend();
      assert.deepEqual(terminated, [9001]);
    }
  } finally {
    if (previousSpawnSetting === undefined) delete process.env.EDMG_STUDIO_SPAWN_BACKEND;
    else process.env.EDMG_STUDIO_SPAWN_BACKEND = previousSpawnSetting;
    if (previousFfmpegPath === undefined) delete process.env.EDMG_FFMPEG_PATH;
    else process.env.EDMG_FFMPEG_PATH = previousFfmpegPath;
  }
});

test("studio UI origin comes from the real dev server URL, not a pinned port", () => {
  assert.equal(
    resolveStudioUiOrigin("http://127.0.0.1:5199/", { isDev: true }),
    "http://127.0.0.1:5199",
  );
  assert.equal(resolveStudioUiOrigin("http://localhost:5173", { isDev: true }), "http://localhost:5173");
  assert.equal(resolveStudioUiOrigin("http://127.0.0.1:5173", { isDev: false }), "null");
});

test("accelerator profile validation is closed and platform-aware", () => {
  assert.equal(normalizeAcceleratorProfile("nvidia", { isWindows: false }), "cuda");
  assert.equal(normalizeAcceleratorProfile("amd", { isWindows: true }), "directml");
  assert.throws(
    () => normalizeAcceleratorProfile("directml", { isWindows: false }),
    /only on Windows/,
  );
  assert.throws(
    () => normalizeAcceleratorProfile("cu132", { isWindows: true }),
    /choose cpu, directml, or cuda/,
  );
});
