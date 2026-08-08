import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

export const LINUX_RELEASE_PROFILES = Object.freeze(["cpu", "cuda"]);

export function parseLinuxReleaseProfile(argv = process.argv.slice(2)) {
  let profile = "";
  for (let index = 0; index < argv.length; index += 1) {
    const argument = String(argv[index] || "");
    if (argument === "--profile") {
      profile = String(argv[index + 1] || "").trim().toLowerCase();
      index += 1;
      continue;
    }
    if (argument.startsWith("--profile=")) {
      profile = argument.slice("--profile=".length).trim().toLowerCase();
    }
  }
  if (!LINUX_RELEASE_PROFILES.includes(profile)) {
    throw new Error(`Linux release profile must be one of ${LINUX_RELEASE_PROFILES.join(", ")}; received ${JSON.stringify(profile)}.`);
  }
  return profile;
}

export function buildLinuxReleaseSteps(profile) {
  if (!LINUX_RELEASE_PROFILES.includes(profile)) {
    throw new Error(`Unsupported Linux release profile: ${profile}`);
  }
  return [
    "validate:desktop",
    profile === "cuda" ? "dist:linux:cuda" : "dist:linux",
    "validate:packaged-appimage-smoke",
  ];
}

export function resolvePackageManagerInvocation({
  env = process.env,
  platform = process.platform,
  nodeExecutable = process.execPath,
  pathExists = fs.existsSync,
} = {}) {
  const npmExecPath = String(env.npm_execpath || "").trim();
  if (npmExecPath && pathExists(npmExecPath)) {
    return { command: nodeExecutable, prefixArgs: [npmExecPath] };
  }
  return { command: platform === "win32" ? "pnpm.cmd" : "pnpm", prefixArgs: [] };
}

export function validateLinuxHost(platform = process.platform) {
  if (platform !== "linux") {
    throw new Error(
      `Linux release validation must run on a native Linux host; current Node platform is ${platform}. ` +
        "A Windows-hosted build can otherwise place a Windows backend launcher inside the Linux package.",
    );
  }
}

export function runLinuxRelease({
  profile,
  env = process.env,
  platform = process.platform,
  spawn = spawnSync,
} = {}) {
  validateLinuxHost(platform);
  if (!LINUX_RELEASE_PROFILES.includes(profile)) {
    throw new Error(`Unsupported Linux release profile: ${profile}`);
  }

  const invocation = resolvePackageManagerInvocation({ env, platform });
  const childEnv = {
    ...env,
    EDMG_BACKEND_ACCELERATOR_PROFILE: profile,
  };

  for (const scriptName of buildLinuxReleaseSteps(profile)) {
    console.log(`[validate-linux-release] running ${scriptName} for ${profile}`);
    const result = spawn(invocation.command, [...invocation.prefixArgs, "run", scriptName], {
      cwd: path.resolve(path.dirname(fileURLToPath(import.meta.url)), ".."),
      env: childEnv,
      shell: false,
      stdio: "inherit",
    });
    if (result.error) throw result.error;
    if (result.status !== 0) {
      throw new Error(`${scriptName} failed with exit code ${result.status ?? "unknown"}.`);
    }
  }

  return { ok: true, profile, steps: buildLinuxReleaseSteps(profile) };
}

function isMainModule() {
  if (!process.argv[1]) return false;
  return path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
}

if (isMainModule()) {
  try {
    const profile = parseLinuxReleaseProfile();
    const result = runLinuxRelease({ profile });
    console.log(JSON.stringify(result, null, 2));
  } catch (error) {
    console.error("[validate-linux-release] FAILED", error);
    process.exitCode = 1;
  }
}
