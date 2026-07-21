import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { writeReleaseEvidence } from "./release-evidence-lib.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const cacheRoot = process.env.EDMG_STUDIO_BUILD_CACHE_ROOT || path.join(root, ".cache");
const electronCache = path.join(cacheRoot, "electron");
const electronBuilderCache = path.join(cacheRoot, "electron-builder");

fs.mkdirSync(electronCache, { recursive: true });
fs.mkdirSync(electronBuilderCache, { recursive: true });

const builderBin = path.join(
  root,
  "node_modules",
  ".bin",
  process.platform === "win32" ? "electron-builder.cmd" : "electron-builder",
);

if (!fs.existsSync(builderBin)) {
  throw new Error(`electron-builder binary not found: ${builderBin}`);
}

const childEnv = {
  ...process.env,
  ELECTRON_CACHE: electronCache,
  ELECTRON_BUILDER_CACHE: electronBuilderCache,
};

async function main() {
  const result =
    process.platform === "win32"
      ? spawnSync("cmd.exe", ["/d", "/s", "/c", builderBin, ...process.argv.slice(2)], {
          cwd: root,
          stdio: "inherit",
          shell: false,
          env: childEnv,
        })
      : spawnSync(builderBin, process.argv.slice(2), {
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
