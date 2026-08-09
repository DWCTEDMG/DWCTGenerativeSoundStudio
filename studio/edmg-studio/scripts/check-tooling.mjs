import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { renderElectronBuilderConfig, root } from "./release-stage-lib.mjs";

const repoRoot = path.resolve(root, "..", "..");
const packageJsonPath = path.join(root, "package.json");
const lockfilePath = path.join(root, "pnpm-lock.yaml");
const electronBuilderPath = path.join(root, "electron-builder.yml");
const backendPyprojectPath = path.join(root, "python_backend", "pyproject.toml");
const backendVersionPath = path.join(root, "python_backend", "edmg_studio_backend", "version.py");
const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
const errors = [];

function extractVersion(filePath, pattern, label) {
  if (!fs.existsSync(filePath)) {
    errors.push(`${label} is missing: ${path.relative(repoRoot, filePath)}`);
    return "";
  }
  const match = fs.readFileSync(filePath, "utf8").match(pattern);
  if (!match?.[1]) {
    errors.push(`${label} does not declare a parseable version: ${path.relative(repoRoot, filePath)}`);
    return "";
  }
  return match[1];
}

function nodeVersionSupported(version) {
  const [major = 0, minor = 0] = String(version || "")
    .split(".")
    .map((part) => Number.parseInt(part, 10) || 0);
  return (major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22;
}

if (!nodeVersionSupported(process.versions.node)) {
  errors.push(
    `Node ${process.versions.node} is unsupported. EDMG Studio requires Node 20.19+ or Node 22.12+ (Node 22 LTS recommended).`,
  );
}

if (!String(packageJson.packageManager || "").startsWith("pnpm@")) {
  errors.push("package.json must declare pnpm as the canonical package manager via packageManager.");
}

if (!packageJson.version || typeof packageJson.version !== "string") {
  errors.push("package.json must declare the shipped desktop version.");
}

const backendProjectVersion = extractVersion(
  backendPyprojectPath,
  /^version\s*=\s*["']([^"']+)["']/m,
  "Backend pyproject",
);
const backendRuntimeVersion = extractVersion(
  backendVersionPath,
  /^STUDIO_VERSION\s*=\s*["']([^"']+)["']/m,
  "Backend runtime version",
);

if (backendProjectVersion && backendProjectVersion !== packageJson.version) {
  errors.push(
    `Backend package version ${backendProjectVersion} does not match desktop version ${packageJson.version}.`,
  );
}

if (backendRuntimeVersion && backendRuntimeVersion !== packageJson.version) {
  errors.push(
    `Backend runtime version ${backendRuntimeVersion} does not match desktop version ${packageJson.version}.`,
  );
}

if (!fs.existsSync(lockfilePath)) {
  errors.push("pnpm-lock.yaml is missing from the Studio package root.");
}

const expectedElectronBuilder = renderElectronBuilderConfig();
const currentElectronBuilder = fs.existsSync(electronBuilderPath)
  ? fs.readFileSync(electronBuilderPath, "utf8")
  : "";

if (currentElectronBuilder !== expectedElectronBuilder) {
  errors.push("electron-builder.yml is out of sync with package.json#build. Regenerate it via the release staging flow.");
}

const gitList = spawnSync("git", ["ls-files", "-z"], {
  cwd: repoRoot,
  encoding: "utf8",
});

if (gitList.status !== 0) {
  errors.push(`Unable to inspect tracked files with git ls-files: ${gitList.stderr || gitList.error || "unknown error"}`);
} else {
  const conflictingLockfiles = gitList.stdout
    .split("\0")
    .filter(Boolean)
    .filter((file) => {
      const base = path.basename(file);
      return base === "package-lock.json" || base === "yarn.lock" || base === "npm-shrinkwrap.json";
    });

  if (conflictingLockfiles.length) {
    errors.push(`Conflicting JS lockfiles are tracked: ${conflictingLockfiles.join(", ")}`);
  }
}

if (!packageJson.build?.win?.artifactName || !String(packageJson.build.win.artifactName).includes("${version}")) {
  errors.push("package.json#build.win.artifactName must include ${version} so packaged installers reflect the canonical app version.");
}

if (errors.length) {
  for (const error of errors) {
    console.error(`[tooling-check] ${error}`);
  }
  process.exit(1);
}

console.log(`[tooling-check] pnpm canonical: ${packageJson.packageManager}`);
console.log(`[tooling-check] node runtime: ${process.versions.node} (${packageJson.engines?.node})`);
console.log(`[tooling-check] shipped desktop version source: ${path.relative(repoRoot, packageJsonPath)}#version (${packageJson.version})`);
console.log(`[tooling-check] backend package/runtime version: ${backendProjectVersion}`);
console.log(`[tooling-check] lockfile: ${path.relative(repoRoot, lockfilePath)}`);
