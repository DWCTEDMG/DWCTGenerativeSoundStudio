import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { finalizeStagedWindowsBackendManifest } from "./windows-backend-signing.mjs";
import { parseBooleanSetting } from "./windows-signing-lib.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const studioRoot = path.resolve(__dirname, "..");

function requireAbsoluteDirectory(value, label) {
  const directory = String(value ?? "").trim();
  if (!directory || !path.isAbsolute(directory)) {
    throw new Error(`${label} must be an absolute directory.`);
  }
  if (!fs.existsSync(directory) || !fs.statSync(directory).isDirectory()) {
    throw new Error(`${label} does not exist: ${directory}`);
  }
  return path.resolve(directory);
}

export function resolvePackagedBackendDirectory(context) {
  const appOutDir = requireAbsoluteDirectory(context?.appOutDir, "Electron Builder appOutDir");
  const backendDirectory = path.resolve(appOutDir, "resources", "backend");
  const relative = path.relative(appOutDir, backendDirectory);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error("The packaged backend directory must remain inside Electron Builder appOutDir.");
  }
  return backendDirectory;
}

function verifyPackagedAuthenticode(backendDirectory, env, spawn = spawnSync) {
  const signScript = path.join(studioRoot, "packaging", "windows", "sign_release.ps1");
  if (!fs.existsSync(signScript) || !fs.statSync(signScript).isFile()) {
    throw new Error(`Windows signing verification script is missing: ${signScript}`);
  }

  for (const executableName of ["edmg-studio-backend.exe", "edmg-hf-bucket-helper.exe"]) {
    const executablePath = path.join(backendDirectory, executableName);
    if (!fs.existsSync(executablePath) || !fs.statSync(executablePath).isFile()) {
      throw new Error(`Packaged Windows executable is missing: ${executablePath}`);
    }
    const result = spawn(
      "powershell.exe",
      [
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        signScript,
        "-StudioDir",
        studioRoot,
        "-ArtifactPaths",
        executablePath,
        "-VerifyOnly",
        "-RequireSigning",
      ],
      {
        cwd: studioRoot,
        stdio: "inherit",
        shell: false,
        env,
      },
    );
    if (result.error) {
      throw new Error(`Packaged Authenticode verification failed: ${result.error.message}`);
    }
    if (result.status !== 0) {
      throw new Error(
        `Packaged Authenticode verification failed with exit code ${result.status ?? "unknown"}.`,
      );
    }
  }
}

export async function finalizeWindowsPackagedBackend(
  context,
  { env = process.env, spawn = spawnSync, finalizedAt } = {},
) {
  if (context?.electronPlatformName !== "win32") {
    return null;
  }

  const signingRequired = parseBooleanSetting(
    env.EDMG_WINDOWS_SIGNING_REQUIRED,
    "EDMG_WINDOWS_SIGNING_REQUIRED",
  );
  const signingConfigured = parseBooleanSetting(
    env.EDMG_WINDOWS_SIGNING_CONFIGURED,
    "EDMG_WINDOWS_SIGNING_CONFIGURED",
  );
  if (signingRequired && !signingConfigured) {
    throw new Error("Required Windows signing reached afterPack without a configured certificate.");
  }

  const backendDirectory = resolvePackagedBackendDirectory(context);
  if (signingConfigured) {
    // electron-builder signs executable extraResources while copying them. Verify
    // those exact packaged bytes before rebasing the embedded provenance hashes.
    verifyPackagedAuthenticode(backendDirectory, env, spawn);
  }

  const manifest = await finalizeStagedWindowsBackendManifest({
    backendDirectory,
    signingRequired,
    signingConfigured,
    ...(finalizedAt ? { finalizedAt } : {}),
  });
  console.log(
    `[electron-builder-after-pack] finalized ${manifest.windowsAuthenticode.status} backend manifest ` +
      `for ${manifest.acceleratorProfile}`,
  );
  return manifest;
}

export default async function afterPack(context) {
  return finalizeWindowsPackagedBackend(context);
}
