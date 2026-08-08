import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { stagePinnedMediaTools } from "./stage-media-tools.mjs";

const root = process.cwd();
const rootMain = path.join(root, "main.mjs");
const rootPreload = path.join(root, "preload.cjs");
const rootMainProcessDir = path.join(root, "main-process");
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const studioRoot = path.resolve(__dirname, "..");
const mediaBinDir = path.join(root, "electron-resources", "bin");

if (!fs.existsSync(rootMain)) throw new Error(`Missing: ${rootMain}`);
if (!fs.existsSync(rootPreload)) throw new Error(`Missing: ${rootPreload}`);
if (!fs.existsSync(rootMainProcessDir)) throw new Error(`Missing: ${rootMainProcessDir}`);

await stagePinnedMediaTools({ root: studioRoot, outDir: mediaBinDir });
console.log("Validated canonical Electron entry files and staged pinned FFmpeg plus FFprobe.");
