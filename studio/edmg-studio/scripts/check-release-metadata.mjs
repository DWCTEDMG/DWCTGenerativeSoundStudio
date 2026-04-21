import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const sourcePackageJsonPath = path.join(root, "package.json");
const stagedPackageJsonPath = path.join(root, "release", "staged-app", "package.json");

const sourcePackageJson = JSON.parse(fs.readFileSync(sourcePackageJsonPath, "utf8"));

if (!fs.existsSync(stagedPackageJsonPath)) {
  console.error("[release-metadata] release/staged-app/package.json is missing. Run `pnpm run release:stage-desktop` first.");
  process.exit(1);
}

const stagedPackageJson = JSON.parse(fs.readFileSync(stagedPackageJsonPath, "utf8"));
const errors = [];

if (stagedPackageJson.name !== sourcePackageJson.name) {
  errors.push(`staged package name ${stagedPackageJson.name} does not match source package name ${sourcePackageJson.name}`);
}

if (stagedPackageJson.version !== sourcePackageJson.version) {
  errors.push(`staged package version ${stagedPackageJson.version} does not match source package version ${sourcePackageJson.version}`);
}

if (stagedPackageJson.main !== sourcePackageJson.main) {
  errors.push(`staged package main ${stagedPackageJson.main} does not match source package main ${sourcePackageJson.main}`);
}

if (errors.length) {
  for (const error of errors) {
    console.error(`[release-metadata] ${error}`);
  }
  process.exit(1);
}

console.log(
  `[release-metadata] ${sourcePackageJson.name}@${sourcePackageJson.version} is staged correctly from package.json into release/staged-app/package.json`,
);
