import assert from "node:assert/strict";
import test from "node:test";

import {
  SOURCE_RUNTIME_CAPABILITY_EXTRAS,
  buildBackendLaunchSpec,
  normalizeAcceleratorProfile,
} from "./backend-runtime.mjs";

const base = {
  resourcesPath: "C:\\Program Files\\EDMG Studio\\resources",
  rootDir: "C:\\src\\studio\\edmg-studio",
  isWindows: true,
  backendHost: "127.0.0.1",
  backendPort: 7863,
};

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
