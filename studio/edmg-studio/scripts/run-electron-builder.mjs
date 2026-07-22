import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

import { writeReleaseEvidence } from "./release-evidence-lib.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const require = createRequire(import.meta.url);
const cacheRoot = process.env.EDMG_STUDIO_BUILD_CACHE_ROOT || path.join(root, ".cache");
const electronCache = path.join(cacheRoot, "electron");
const electronBuilderCache = path.join(cacheRoot, "electron-builder");

fs.mkdirSync(electronCache, { recursive: true });
fs.mkdirSync(electronBuilderCache, { recursive: true });

const builderEntry = require.resolve("electron-builder/cli.js");

if (!fs.existsSync(builderEntry)) {
  throw new Error(`electron-builder entry point not found: ${builderEntry}`);
}

const childEnv = {
  ...process.env,
  ELECTRON_CACHE: electronCache,
  ELECTRON_BUILDER_CACHE: electronBuilderCache,
};

async function main() {
  const result = spawnSync(process.execPath, [builderEntry, ...process.argv.slice(2)], {
    cwd: root,
    stdio: "inherit",
    shell: false,
    env: childEnv,
  });

  if (result.error) {
    throw result.error;
  }

  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }

  const wantsInstallerArtifacts = process.argv.slice(2).some(
    (arg) => /^-w/i.test(arg) || /^--win/i.test(arg) || /^-l/i.test(arg) || /^--linux/i.test(arg),
  );
  if (!wantsInstallerArtifacts) {
    return;
  }

  const packageJson = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
  const evidence = await writeReleaseEvidence({
    root,
    phase: "dist",
    profile: process.env.EDMG_BACKEND_ACCELERATOR_PROFILE || "",
    version: String(packageJson.version || ""),
    env: process.env,
  });
  console.log(
    `[run-electron-builder] release evidence written: ${path.relative(root, evidence.indexPath).split(path.sep).join("/")}`,
  );
}

main().catch((error) => {
  console.error("[run-electron-builder] release evidence generation failed", error);
  process.exit(1);
});
