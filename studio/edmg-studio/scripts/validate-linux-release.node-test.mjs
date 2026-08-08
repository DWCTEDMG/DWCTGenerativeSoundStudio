import assert from "node:assert/strict";
import test from "node:test";

import {
  buildLinuxReleaseSteps,
  parseLinuxReleaseProfile,
  resolvePackageManagerInvocation,
  runLinuxRelease,
  validateLinuxHost,
} from "./validate-linux-release.mjs";

test("Linux release profile parser accepts only explicit cpu or cuda profiles", () => {
  assert.equal(parseLinuxReleaseProfile(["--profile", "cpu"]), "cpu");
  assert.equal(parseLinuxReleaseProfile(["--profile=CUDA"]), "cuda");
  assert.throws(() => parseLinuxReleaseProfile([]), /must be one of cpu, cuda/);
  assert.throws(() => parseLinuxReleaseProfile(["--profile", "directml"]), /must be one of cpu, cuda/);
});

test("Linux CUDA validation builds and then smokes the final AppImage", () => {
  assert.deepEqual(buildLinuxReleaseSteps("cuda"), [
    "validate:desktop",
    "dist:linux:cuda",
    "validate:packaged-appimage-smoke",
  ]);
  assert.deepEqual(buildLinuxReleaseSteps("cpu"), [
    "validate:desktop",
    "dist:linux",
    "validate:packaged-appimage-smoke",
  ]);
});

test("Linux release validation fails closed on a non-Linux host", () => {
  assert.throws(() => validateLinuxHost("win32"), /must run on a native Linux host/);
  assert.doesNotThrow(() => validateLinuxHost("linux"));
});

test("package manager invocation uses npm_execpath without a shell when available", () => {
  assert.deepEqual(
    resolvePackageManagerInvocation({
      env: { npm_execpath: "/opt/pnpm/pnpm.cjs" },
      platform: "linux",
      nodeExecutable: "/usr/bin/node",
      pathExists: () => true,
    }),
    { command: "/usr/bin/node", prefixArgs: ["/opt/pnpm/pnpm.cjs"] },
  );
});

test("Linux release runner keeps one accelerator profile across every ordered gate", () => {
  const calls = [];
  const spawn = (command, args, options) => {
    calls.push({ command, args, options });
    return { status: 0 };
  };
  const result = runLinuxRelease({
    profile: "cuda",
    platform: "linux",
    env: {},
    spawn,
  });
  assert.equal(result.ok, true);
  assert.deepEqual(calls.map((call) => call.args.slice(-2)), [
    ["run", "validate:desktop"],
    ["run", "dist:linux:cuda"],
    ["run", "validate:packaged-appimage-smoke"],
  ]);
  assert.ok(calls.every((call) => call.options.shell === false));
  assert.ok(calls.every((call) => call.options.env.EDMG_BACKEND_ACCELERATOR_PROFILE === "cuda"));
});

test("Linux release runner stops on the first failed gate", () => {
  let callCount = 0;
  assert.throws(
    () =>
      runLinuxRelease({
        profile: "cpu",
        platform: "linux",
        env: {},
        spawn: () => {
          callCount += 1;
          return { status: 23 };
        },
      }),
    /validate:desktop failed with exit code 23/,
  );
  assert.equal(callCount, 1);
});
