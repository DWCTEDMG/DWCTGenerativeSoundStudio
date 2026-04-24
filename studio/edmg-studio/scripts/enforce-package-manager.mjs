import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const packageJsonPath = path.join(root, "package.json");
const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
const expectedPackageManager = String(packageJson.packageManager || "pnpm").trim();
const userAgent = String(process.env.npm_config_user_agent || "").trim().toLowerCase();
const execPath = String(process.env.npm_execpath || "").trim().toLowerCase();

const isPnpm = userAgent.startsWith("pnpm/") || execPath.includes("pnpm");

if (isPnpm) {
  process.exit(0);
}

console.error(`This package must be installed with ${expectedPackageManager}.`);
console.error("Run `corepack enable` once if `pnpm` is unavailable, then rerun `pnpm install` from `studio/edmg-studio/`.");
process.exit(1);
