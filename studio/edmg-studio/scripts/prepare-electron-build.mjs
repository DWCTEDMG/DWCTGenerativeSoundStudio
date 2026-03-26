import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = process.cwd();
const rootMain = path.join(root, "main.mjs");
const rootPreload = path.join(root, "preload.cjs");
const rootMainProcessDir = path.join(root, "main-process");
const electronDir = path.join(root, "electron");
const electronMain = path.join(electronDir, "main.mjs");
const electronPreload = path.join(electronDir, "preload.cjs");
const electronMainProcessDir = path.join(electronDir, "main-process");
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..", "..", "..");
const ffmpegBinDir = path.join(root, "electron-resources", "bin");
const ffmpegExe = path.join(ffmpegBinDir, process.platform === "win32" ? "ffmpeg.exe" : "ffmpeg");

if (!fs.existsSync(rootMain)) throw new Error(`Missing: ${rootMain}`);
if (!fs.existsSync(rootPreload)) throw new Error(`Missing: ${rootPreload}`);
if (!fs.existsSync(rootMainProcessDir)) throw new Error(`Missing: ${rootMainProcessDir}`);

function ensureBundledFfmpeg() {
  if (fs.existsSync(ffmpegExe)) return;
  if (process.platform !== "win32") return;

  const script = path.join(repoRoot, "packaging", "windows", "get_ffmpeg.ps1");
  if (!fs.existsSync(script)) {
    throw new Error(`Missing FFmpeg staging script: ${script}`);
  }

  fs.mkdirSync(ffmpegBinDir, { recursive: true });
  const result = spawnSync(
    "powershell",
    [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      script,
      "-OutDir",
      "./studio/edmg-studio/electron-resources/bin",
    ],
    {
      cwd: repoRoot,
      stdio: "inherit",
    }
  );

  if (result.status !== 0 || !fs.existsSync(ffmpegExe)) {
    throw new Error(`Failed to stage bundled FFmpeg via ${script}`);
  }
}

ensureBundledFfmpeg();

fs.mkdirSync(electronDir, { recursive: true });
fs.copyFileSync(rootMain, electronMain);
fs.copyFileSync(rootPreload, electronPreload);
fs.rmSync(electronMainProcessDir, { recursive: true, force: true });
fs.cpSync(rootMainProcessDir, electronMainProcessDir, { recursive: true });

console.log("Validated root Electron entry files, ensured bundled FFmpeg, and synced mirror copies under electron/.");
