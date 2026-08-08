import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  RELEASE_CANDIDATE_SCRIPT,
  createProductionReleasePlan,
  resolvePackageManagerInvocation,
  runProductionRelease,
} from "./validate-production-release.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const studioRoot = path.resolve(__dirname, "..");
const thumbprint = "0123456789ABCDEF0123456789ABCDEF01234567";

test("package scripts keep the local candidate gate distinct from the fail-closed production gate", () => {
  const packageJson = JSON.parse(fs.readFileSync(path.join(studioRoot, "package.json"), "utf8"));
  const candidate = String(packageJson.scripts?.[RELEASE_CANDIDATE_SCRIPT] ?? "");
  const production = String(packageJson.scripts?.["validate:release:production"] ?? "");

  assert.match(candidate, /pnpm run validate:desktop/);
  assert.match(candidate, /pnpm run dist:win/);
  assert.doesNotMatch(candidate, /EDMG_REQUIRE_CODE_SIGNING|validate-production-release/);
  assert.equal(production, "node scripts/validate-production-release.mjs");
});

test("production signing preflight fails before spawning the expensive candidate gate", () => {
  let spawnCount = 0;
  assert.throws(
    () => runProductionRelease({
      root: studioRoot,
      env: {},
      platform: "linux",
      spawnSyncImpl: () => {
        spawnCount += 1;
        return { status: 0 };
      },
      log: () => {},
    }),
    /EDMG_CODE_SIGN_CERT is not configured/,
  );
  assert.equal(spawnCount, 0);
});

test("production release forces signing and invokes the unchanged candidate script", () => {
  const packageManagerCli = path.join(studioRoot, "fixtures", "pnpm.cjs");
  let invocation;
  const status = runProductionRelease({
    root: studioRoot,
    platform: "win32",
    nodeExecPath: "C:\\Program Files\\nodejs\\node.exe",
    env: {
      npm_execpath: packageManagerCli,
      EDMG_CODE_SIGN_CERT: thumbprint,
      EDMG_REQUIRE_CODE_SIGNING: "0",
    },
    spawnSyncImpl: (command, args, options) => {
      invocation = { command, args, options };
      return { status: 0 };
    },
    log: () => {},
  });

  assert.equal(status, 0);
  assert.equal(invocation.command, "C:\\Program Files\\nodejs\\node.exe");
  assert.deepEqual(invocation.args, [packageManagerCli, "run", RELEASE_CANDIDATE_SCRIPT]);
  assert.equal(invocation.options.cwd, studioRoot);
  assert.equal(invocation.options.env.EDMG_REQUIRE_CODE_SIGNING, "1");
  assert.equal(invocation.options.env.EDMG_CODE_SIGN_CERT, thumbprint);
  assert.equal(invocation.options.shell, false);
});

test("production preflight delegates timestamp validation to the Windows signing policy", () => {
  assert.throws(
    () => createProductionReleasePlan({
      root: studioRoot,
      env: {
        EDMG_CODE_SIGN_CERT: thumbprint,
        EDMG_CODE_SIGN_TIMESTAMP_URL: "file:///not-a-timestamp-service",
      },
      platform: "linux",
    }),
    /EDMG_CODE_SIGN_TIMESTAMP_URL must use HTTP or HTTPS/,
  );
});

test("package-manager invocation avoids Node shell mode on Windows and POSIX", () => {
  assert.deepEqual(
    resolvePackageManagerInvocation({
      env: { ComSpec: "C:\\Windows\\System32\\cmd.exe" },
      platform: "win32",
      nodeExecPath: "node.exe",
    }),
    {
      command: "C:\\Windows\\System32\\cmd.exe",
      args: ["/d", "/s", "/c", `pnpm run ${RELEASE_CANDIDATE_SCRIPT}`],
    },
  );
  assert.deepEqual(
    resolvePackageManagerInvocation({ env: {}, platform: "linux", nodeExecPath: "/usr/bin/node" }),
    { command: "pnpm", args: ["run", RELEASE_CANDIDATE_SCRIPT] },
  );
});
