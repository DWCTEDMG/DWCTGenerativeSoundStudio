import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { resolveWindowsSigningPlan } from "./windows-signing-lib.mjs";

export const RELEASE_CANDIDATE_SCRIPT = "validate:release";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const studioRoot = path.resolve(__dirname, "..");

export function resolvePackageManagerInvocation({
  env = process.env,
  platform = process.platform,
  nodeExecPath = process.execPath,
} = {}) {
  const packageManagerCli = String(env.npm_execpath ?? "").trim();
  if (packageManagerCli && /\.(?:c|m)?js$/i.test(packageManagerCli)) {
    return {
      command: nodeExecPath,
      args: [packageManagerCli, "run", RELEASE_CANDIDATE_SCRIPT],
    };
  }

  if (platform === "win32") {
    return {
      command: String(env.ComSpec || env.COMSPEC || "cmd.exe"),
      args: ["/d", "/s", "/c", `pnpm run ${RELEASE_CANDIDATE_SCRIPT}`],
    };
  }

  return {
    command: "pnpm",
    args: ["run", RELEASE_CANDIDATE_SCRIPT],
  };
}

export function createProductionReleasePlan({
  root = studioRoot,
  env = process.env,
  platform = process.platform,
  nodeExecPath = process.execPath,
} = {}) {
  const productionEnv = {
    ...env,
    EDMG_REQUIRE_CODE_SIGNING: "1",
  };

  // Use the same policy as electron-builder. Supplying an explicit Windows
  // target makes this preflight fail before the candidate gate starts, even
  // when the wrapper itself is invoked from a non-Windows automation host.
  const signingPlan = resolveWindowsSigningPlan({
    root,
    builderArgs: ["--win"],
    env: productionEnv,
    platform,
  });

  return {
    invocation: resolvePackageManagerInvocation({ env, platform, nodeExecPath }),
    childEnv: signingPlan.childEnv,
    certificateKind: signingPlan.certificateKind,
  };
}

export function runProductionRelease({
  root = studioRoot,
  env = process.env,
  platform = process.platform,
  nodeExecPath = process.execPath,
  spawnSyncImpl = spawnSync,
  log = console.log,
} = {}) {
  const plan = createProductionReleasePlan({ root, env, platform, nodeExecPath });
  log(
    `[validate-production-release] Fail-closed production gate: ${plan.certificateKind} signing credentials passed preflight. ` +
      `Invoking pnpm run ${RELEASE_CANDIDATE_SCRIPT} with EDMG_REQUIRE_CODE_SIGNING=1.`,
  );

  const result = spawnSyncImpl(plan.invocation.command, plan.invocation.args, {
    cwd: root,
    env: plan.childEnv,
    stdio: "inherit",
    shell: false,
    windowsHide: true,
  });
  if (result.error) {
    throw new Error(`Unable to start the production release gate: ${result.error.message}`);
  }
  return result.status ?? 1;
}

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : "";
if (invokedPath === fileURLToPath(import.meta.url)) {
  try {
    process.exitCode = runProductionRelease();
  } catch (error) {
    console.error(`[validate-production-release] FAILED: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  }
}
