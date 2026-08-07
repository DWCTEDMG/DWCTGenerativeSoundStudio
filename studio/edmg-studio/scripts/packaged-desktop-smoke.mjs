import assert from "node:assert/strict";
import fs from "node:fs";
import fsp from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import {
  RELEASE_CAPABILITY_EXTRAS,
  assertValidReleaseManifest,
  sha256File,
} from "./release-python-toolchain.mjs";
import { resolvePinnedMediaAsset } from "./stage-media-tools.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");

function log(msg) {
  console.log(`[packaged-desktop-smoke] ${msg}`);
}

function canLaunchElectron() {
  if (process.platform === "linux" && !process.env.DISPLAY && !process.env.WAYLAND_DISPLAY) {
    const xvfb = "/usr/bin/xvfb-run";
    if (!fs.existsSync(xvfb)) {
      return { ok: false, reason: "No DISPLAY/WAYLAND session and xvfb-run not available for unpacked desktop launch." };
    }
  }
  return { ok: true, reason: "Unpacked desktop launch supported" };
}

import { assertDesktopArtifacts, stageDesktopRelease } from './release-stage-lib.mjs';

function bundledResourcePaths(appDir) {
  return {
    backendExe: path.join(appDir, "electron-resources", "backend", process.platform === "win32" ? "edmg-studio-backend.exe" : "edmg-studio-backend"),
    backendManifest: path.join(appDir, "electron-resources", "backend", "backend-bundle-manifest.json"),
    ffmpegExe: path.join(appDir, "electron-resources", "bin", process.platform === "win32" ? "ffmpeg.exe" : "ffmpeg"),
    ffprobeExe: path.join(appDir, "electron-resources", "bin", process.platform === "win32" ? "ffprobe.exe" : "ffprobe"),
    ffmpegLicense: path.join(appDir, "electron-resources", "bin", "FFmpeg-LICENSE.txt"),
    ffmpegSourceNotice: path.join(appDir, "electron-resources", "bin", "FFmpeg-SOURCE.txt"),
  };
}

function assertRunnableBundledMediaTool(toolPath, toolName) {
  assert.ok(fs.existsSync(toolPath), `staged app missing bundled ${toolName}: ${toolPath}`);
  const stat = fs.statSync(toolPath);
  assert.ok(stat.isFile() && stat.size > 0, `staged app bundled ${toolName} is empty or not a file: ${toolPath}`);
  const result = spawnSync(toolPath, ["-version"], {
    encoding: "utf8",
    maxBuffer: 2 * 1024 * 1024,
    timeout: 15000,
    windowsHide: true,
  });
  if (result.error) throw result.error;
  const output = `${result.stdout || ""}\n${result.stderr || ""}`;
  assert.equal(result.status, 0, `staged app bundled ${toolName} failed its version probe: ${output.trim()}`);
  assert.match(output, new RegExp(`^${toolName} version`, "im"));
}

function assertBundledMediaDistributionEvidence(resources) {
  const asset = resolvePinnedMediaAsset({ platform: process.platform, arch: process.arch });
  for (const [label, filePath] of [
    ["FFmpeg license", resources.ffmpegLicense],
    ["FFmpeg source notice", resources.ffmpegSourceNotice],
  ]) {
    assert.ok(fs.existsSync(filePath), `staged app missing bundled ${label}: ${filePath}`);
    const stat = fs.statSync(filePath);
    assert.ok(stat.isFile() && stat.size > 0, `staged app bundled ${label} is empty or not a file: ${filePath}`);
  }

  const licenseText = fs.readFileSync(resources.ffmpegLicense, "utf8");
  assert.match(licenseText, /GNU GENERAL PUBLIC LICENSE[\s\S]{0,200}Version 3/i);

  const sourceNotice = fs.readFileSync(resources.ffmpegSourceNotice, "utf8");
  for (const expectedValue of [
    asset.releaseTag,
    asset.archiveName,
    asset.sha256,
    asset.distributionNotice.ffmpegSource.commit,
    asset.distributionNotice.buildSource.commit,
  ]) {
    assert.ok(
      sourceNotice.includes(expectedValue),
      `staged app FFmpeg source notice does not identify ${expectedValue}`,
    );
  }
  return {
    license: resources.ffmpegLicense,
    sourceNotice: resources.ffmpegSourceNotice,
    archiveSha256: asset.sha256,
  };
}

function resolveUnpackedApp(outputDir) {
  const candidates = [
    path.join(outputDir, "win-unpacked", process.platform === "win32" ? "EDMG Studio.exe" : "EDMG Studio"),
    path.join(outputDir, "linux-unpacked", "edmg-studio"),
    path.join(outputDir, "mac", "EDMG Studio.app", "Contents", "MacOS", "EDMG Studio"),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return "";
}

async function buildUnpackedDesktopApp(appDir, outputDir) {
  await fsp.rm(outputDir, { recursive: true, force: true });
  const builderScript = path.join(root, "scripts", "run-electron-builder.mjs");
  const result = spawnSync(
    process.execPath,
    [
      builderScript,
      "--dir",
      `-c.directories.app=${appDir}`,
      `-c.directories.output=${outputDir}`,
    ],
    {
      cwd: root,
      stdio: "inherit",
      env: process.env,
    },
  );

  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`electron-builder --dir failed with exit code ${result.status}`);
  }

  const unpackedApp = resolveUnpackedApp(outputDir);
  assert.ok(unpackedApp, `Unpacked app not found under ${outputDir}`);
  return unpackedApp;
}

async function startMockBackend() {
  const server = http.createServer((req, res) => {
    if (req.url === "/health") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ ok: true, service: "packaged-desktop-smoke-mock" }));
      return;
    }
    res.writeHead(404, { "content-type": "application/json" });
    res.end(JSON.stringify({ ok: false, error: { message: "Not found" } }));
  });
  await new Promise((resolve, reject) => {
    server.listen(0, "127.0.0.1", () => resolve());
    server.on("error", reject);
  });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Unable to bind mock backend");
  return { server, port: address.port };
}

function buildIsolatedDesktopEnv(fixtureRoot) {
  const appDataDir = path.join(fixtureRoot, "appdata", "Roaming");
  const localAppDataDir = path.join(fixtureRoot, "appdata", "Local");
  const studioHome = path.join(fixtureRoot, "studio-home");
  return {
    APPDATA: appDataDir,
    LOCALAPPDATA: localAppDataDir,
    EDMG_STUDIO_HOME: studioHome,
  };
}

async function probeBundledBackendRunJobCli(backendExe) {
  const fixtureRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-packaged-backend-cli-"));
  const projectId = "packaged-cli-probe-project";
  const jobId = "packaged-cli-probe-job";
  try {
    const result = spawnSync(
      backendExe,
      ["run-job", "--project", projectId, "--job", jobId],
      {
        cwd: path.dirname(backendExe),
        encoding: "utf8",
        env: {
          ...process.env,
          EDMG_AI_PROVIDER: "rule_based",
          EDMG_STUDIO_SPAWN_BACKEND: "0",
          ...buildIsolatedDesktopEnv(fixtureRoot),
        },
        maxBuffer: 4 * 1024 * 1024,
        timeout: 120000,
        windowsHide: true,
      },
    );

    if (result.error) throw result.error;
    const output = `${result.stdout || ""}\n${result.stderr || ""}`;
    assert.equal(
      result.status,
      2,
      `Bundled backend missing-job CLI probe should exit 2, received ${result.status}: ${output}`,
    );
    assert.match(
      output,
      new RegExp(`Job not found: project=${projectId} job=${jobId}`),
      `Bundled backend did not reach the run-job handler: ${output}`,
    );
    assert.doesNotMatch(
      output,
      /invalid choice:\s*['"]?edmg_studio_backend/i,
      "Bundled backend must receive run-job directly, without the source-only '-m edmg_studio_backend' prefix",
    );
    return { ok: true, expectedExitCode: 2, projectId, jobId };
  } finally {
    await fsp.rm(fixtureRoot, { recursive: true, force: true });
  }
}

async function waitForFile(filePath, timeoutMs = 20000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (fs.existsSync(filePath) && fs.statSync(filePath).size > 0) return;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`Timed out waiting for ${filePath}`);
}

async function runStagedAppProbe() {
  const support = canLaunchElectron();
  const smokeStageDir = path.join(root, "release", "staged-app-smoke");
  const smokeOutputDir = path.join(root, "release", "desktop-smoke-dist");
  const stageManifest = await stageDesktopRelease({ outDir: smokeStageDir, clean: true });
  const appDir = stageManifest.stageDir;
  const unpackedApp = await buildUnpackedDesktopApp(appDir, smokeOutputDir);
  const summary = {
    ok: true,
    skipped: !support.ok,
    reason: support.reason,
    appDir,
    smokeOutputDir,
    unpackedApp,
    stageManifestPath: path.join(appDir, '.edmg-stage', 'manifest.json'),
  };
  const resources = bundledResourcePaths(appDir);

  const distIndex = path.join(appDir, "dist-web", "index.html");
  assert.ok(fs.existsSync(distIndex), "staged app dist-web/index.html missing");
  assert.ok(fs.existsSync(path.join(appDir, 'electron-builder.yml')), 'staged app electron-builder.yml missing');
  assert.ok(fs.existsSync(resources.backendExe), `staged app missing bundled backend: ${resources.backendExe}`);
  assert.ok(fs.existsSync(resources.backendManifest), `staged app missing backend bundle manifest: ${resources.backendManifest}`);
  const bundledFfmpeg = fs.existsSync(resources.ffmpegExe) && fs.statSync(resources.ffmpegExe).isFile();
  const bundledFfprobe = fs.existsSync(resources.ffprobeExe) && fs.statSync(resources.ffprobeExe).isFile();
  if (process.platform === "win32" || process.platform === "linux") {
    assertRunnableBundledMediaTool(resources.ffmpegExe, "ffmpeg");
    assertRunnableBundledMediaTool(resources.ffprobeExe, "ffprobe");
    summary.mediaDistributionEvidence = assertBundledMediaDistributionEvidence(resources);
  }
  const backendManifest = JSON.parse(await fsp.readFile(resources.backendManifest, "utf8"));
  assertValidReleaseManifest(backendManifest);
  assert.equal(
    await sha256File(resources.backendExe),
    backendManifest.binarySha256,
    "backend binary hash must match its release manifest",
  );
  assert.equal(
    await sha256File(path.join(root, "python_backend", "uv.lock")),
    backendManifest.lockSha256,
    "backend release manifest must match the committed uv.lock",
  );
  assert.ok(
    Array.isArray(backendManifest.requiredBackendSources) &&
      backendManifest.requiredBackendSources.includes("edmg_studio_backend/services/internal_video.py") &&
      backendManifest.requiredBackendSources.includes("edmg_studio_backend/services/internal_video_models.py"),
    "backend bundle manifest must prove internal video source modules were included",
  );
  assert.deepEqual(
    backendManifest.capabilityExtras,
    RELEASE_CAPABILITY_EXTRAS,
    "backend release manifest must preserve the deterministic capability extras",
  );
  summary.resources = resources;
  summary.ffmpegMode = bundledFfmpeg && bundledFfprobe ? "bundled-ffmpeg-and-ffprobe" : "unsupported-platform-fallback";
  summary.backendManifest = backendManifest;
  summary.backendRunJobCli = await probeBundledBackendRunJobCli(resources.backendExe);

  if (!support.ok) {
    return summary;
  }

  const fixtureRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-packaged-probe-"));
  const fixtureDir = path.join(fixtureRoot, "frames");
  await fsp.mkdir(fixtureDir, { recursive: true });
  const fixtureFile = path.join(fixtureRoot, "demo.txt");
  await fsp.writeFile(fixtureFile, "packaged desktop smoke probe\n");
  const reportPath = path.join(fixtureRoot, "report.json");
  const isolatedEnv = buildIsolatedDesktopEnv(fixtureRoot);

  const { server, port } = await startMockBackend();
  const expectedBackendUrl = `http://127.0.0.1:${port}`;

  const args = [];
  let cmd = unpackedApp;
  if (process.platform === "linux" && !process.env.DISPLAY && !process.env.WAYLAND_DISPLAY && fs.existsSync("/usr/bin/xvfb-run")) {
    cmd = "/usr/bin/xvfb-run";
    args.push("-a", unpackedApp);
  }

  log(`launching staged app probe using ${cmd}`);
  const child = spawn(cmd, args, {
    cwd: path.dirname(unpackedApp),
    env: {
      ...process.env,
      EDMG_STUDIO_TEST_MODE: "1",
      EDMG_STUDIO_TEST_SKIP_MIGRATION: "1",
      EDMG_STUDIO_TEST_REPORT_PATH: reportPath,
      EDMG_STUDIO_TEST_PROBE_REVEAL_PATH: fixtureFile,
      EDMG_STUDIO_TEST_PROBE_OPEN_PATH: fixtureDir,
      EDMG_STUDIO_TEST_EXPECT_BACKEND_URL: expectedBackendUrl,
      EDMG_STUDIO_TEST_FAKE_PATH_ACTIONS: "1",
      EDMG_STUDIO_SPAWN_BACKEND: "0",
      EDMG_STUDIO_BACKEND_PORT: String(port),
      ELECTRON_DISABLE_SECURITY_WARNINGS: "1",
      ...isolatedEnv,
    },
    stdio: "inherit",
  });

  let exitCode = null;
  child.on("exit", (code) => {
    exitCode = code;
  });

  try {
    await waitForFile(reportPath, 25000);
    const report = JSON.parse(await fsp.readFile(reportPath, "utf8"));
    assert.equal(report.ok, true, `Staged app probe failed: ${JSON.stringify(report)}`);
    assert.equal(report.backendUrlSync, expectedBackendUrl);
    assert.equal(report.backendUrlAsync, expectedBackendUrl);
    assert.equal(report.reveal?.ok, true);
    assert.equal(report.open?.ok, true);
    return { ...summary, skipped: false, report };
  } finally {
    server.close();
    if (exitCode === null) child.kill("SIGTERM");
  }
}

async function main() {
  if (process.argv.slice(2).includes("--backend-cli-only")) {
    const backendExe = bundledResourcePaths(root).backendExe;
    assert.ok(fs.existsSync(backendExe), `Bundled backend not found: ${backendExe}`);
    const backendRunJobCli = await probeBundledBackendRunJobCli(backendExe);
    log("bundled backend run-job CLI probe passed");
    console.log(JSON.stringify({ ok: true, backendRunJobCli }, null, 2));
    return;
  }

  assertDesktopArtifacts();
  log("build artifact checks passed");

  const stagedProbe = await runStagedAppProbe();
  if (stagedProbe.skipped) {
    log(`staged app probe skipped: ${stagedProbe.reason}`);
  } else {
    log("staged app probe passed");
  }

  console.log(JSON.stringify({ ok: true, buildArtifacts: true, stagedProbe }, null, 2));
}

main().catch((error) => {
  console.error("[packaged-desktop-smoke] FAILED", error);
  process.exit(1);
});
