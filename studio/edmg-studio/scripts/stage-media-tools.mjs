import crypto from "node:crypto";
import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { spawnSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const studioRoot = path.resolve(__dirname, "..");
export const mediaAssetManifestPath = path.join(studioRoot, "packaging", "media-tools-assets.json");

function isSha256(value) {
  return /^[a-f0-9]{64}$/i.test(String(value ?? ""));
}

function isFullGitCommit(value) {
  return /^(?:[a-f0-9]{40}|[a-f0-9]{64})$/i.test(String(value ?? ""));
}

function assertSafeLeafName(value, label) {
  const name = String(value ?? "").trim();
  if (!name || path.basename(name) !== name || name === "." || name === "..") {
    throw new Error(`${label} must be a safe file name`);
  }
  return name;
}

function assertCommitSource(value, urlValue, label) {
  const commit = String(value ?? "").trim().toLowerCase();
  if (!isFullGitCommit(commit)) throw new Error(`${label}Commit must be a full Git commit digest`);
  const url = new URL(String(urlValue ?? ""));
  if (url.protocol !== "https:" || !url.pathname.toLowerCase().includes(commit)) {
    throw new Error(`${label}Url must be an HTTPS URL containing ${commit}`);
  }
  return { commit, url: url.href };
}

export function loadPinnedMediaManifest(manifestPath = mediaAssetManifestPath) {
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  if (manifest?.schemaVersion !== 1) {
    throw new Error(`Unsupported media asset manifest schema: ${manifest?.schemaVersion ?? "missing"}`);
  }
  if (!/^autobuild-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}$/.test(String(manifest.releaseTag ?? ""))) {
    throw new Error("Media asset manifest releaseTag must be an immutable BtbN autobuild tag");
  }
  if (!manifest.assets || typeof manifest.assets !== "object") {
    throw new Error("Media asset manifest must define platform assets");
  }
  if (!manifest.distributionNotice || typeof manifest.distributionNotice !== "object") {
    throw new Error("Media asset manifest must define redistribution license and source notice metadata");
  }
  return manifest;
}

export function resolvePinnedMediaAsset({
  platform = process.platform,
  arch = process.arch,
  manifest = loadPinnedMediaManifest(),
} = {}) {
  const key = `${platform}-${arch}`;
  const raw = manifest.assets?.[key];
  if (!raw) {
    throw new Error(`No pinned FFmpeg/FFprobe asset is configured for ${key}`);
  }

  const sourceRepositoryUrl = new URL(String(manifest.sourceRepository ?? ""));
  if (
    sourceRepositoryUrl.protocol !== "https:" ||
    sourceRepositoryUrl.username ||
    sourceRepositoryUrl.password ||
    sourceRepositoryUrl.search ||
    sourceRepositoryUrl.hash
  ) {
    throw new Error("Media asset sourceRepository must be a plain HTTPS repository URL");
  }
  const sourceRepositoryPath = sourceRepositoryUrl.pathname.replace(/\/+$/, "");
  const ffmpegVersion = String(manifest.ffmpegVersion ?? "").trim();
  if (!ffmpegVersion) throw new Error("Media asset manifest ffmpegVersion is required");

  const archiveName = assertSafeLeafName(raw.archiveName, `${key}.archiveName`);
  if (!archiveName.startsWith(`ffmpeg-${ffmpegVersion}-`) || !/-gpl(?:-|\.|$)/i.test(archiveName)) {
    throw new Error(`${key}.archiveName must identify the pinned ${ffmpegVersion} GPL build`);
  }
  const archiveFormat = String(raw.archiveFormat ?? "");
  if (!new Set(["zip", "tar.xz"]).has(archiveFormat)) {
    throw new Error(`${key}.archiveFormat must be zip or tar.xz`);
  }
  const url = new URL(String(raw.url ?? ""));
  if (url.protocol !== "https:" || path.posix.basename(url.pathname) !== archiveName) {
    throw new Error(`${key}.url must be an HTTPS URL ending in ${archiveName}`);
  }
  const immutableReleasePrefix = `${sourceRepositoryPath}/releases/download/${manifest.releaseTag}/`;
  if (url.origin !== sourceRepositoryUrl.origin || !url.pathname.startsWith(immutableReleasePrefix)) {
    throw new Error(`${key}.url must use ${manifest.sourceRepository} release ${manifest.releaseTag}`);
  }
  if (!Number.isSafeInteger(raw.size) || raw.size <= 0) {
    throw new Error(`${key}.size must be a positive integer`);
  }
  if (!isSha256(raw.sha256)) {
    throw new Error(`${key}.sha256 must be a SHA-256 digest`);
  }

  const expectedSuffix = platform === "win32" ? ".exe" : "";
  const binaryNames = {
    ffmpeg: assertSafeLeafName(raw.binaryNames?.ffmpeg, `${key}.binaryNames.ffmpeg`),
    ffprobe: assertSafeLeafName(raw.binaryNames?.ffprobe, `${key}.binaryNames.ffprobe`),
  };
  if (binaryNames.ffmpeg !== `ffmpeg${expectedSuffix}` || binaryNames.ffprobe !== `ffprobe${expectedSuffix}`) {
    throw new Error(`${key} must provide the canonical ffmpeg and ffprobe binary names`);
  }

  const rawNotice = manifest.distributionNotice;
  const ffmpegSource = assertCommitSource(
    rawNotice.ffmpegSourceCommit,
    rawNotice.ffmpegSourceUrl,
    "distributionNotice.ffmpegSource",
  );
  const buildSource = assertCommitSource(
    rawNotice.buildSourceCommit,
    rawNotice.buildSourceUrl,
    "distributionNotice.buildSource",
  );
  const distributionNotice = {
    licenseArchiveName: assertSafeLeafName(
      rawNotice.licenseArchiveName,
      "distributionNotice.licenseArchiveName",
    ),
    licenseOutputName: assertSafeLeafName(
      rawNotice.licenseOutputName,
      "distributionNotice.licenseOutputName",
    ),
    sourceNoticeOutputName: assertSafeLeafName(
      rawNotice.sourceNoticeOutputName,
      "distributionNotice.sourceNoticeOutputName",
    ),
    licenseName: String(rawNotice.licenseName ?? "").trim(),
    ffmpegSource,
    buildSource,
  };
  if (!distributionNotice.licenseName) {
    throw new Error("distributionNotice.licenseName is required");
  }
  const outputNames = new Set([
    ...Object.values(binaryNames).map((name) => name.toLowerCase()),
    distributionNotice.licenseOutputName.toLowerCase(),
    distributionNotice.sourceNoticeOutputName.toLowerCase(),
  ]);
  if (outputNames.size !== 4) {
    throw new Error(`${key} media binary and distribution notice output names must be unique`);
  }

  return {
    key,
    archiveName,
    archiveFormat,
    url: url.href,
    size: raw.size,
    sha256: raw.sha256.toLowerCase(),
    binaryNames,
    releaseTag: manifest.releaseTag,
    ffmpegVersion,
    sourceRepository: sourceRepositoryUrl.href.replace(/\/+$/, ""),
    distributionNotice,
  };
}

export function renderMediaSourceNotice(asset) {
  const notice = asset.distributionNotice;
  return [
    "FFmpeg and FFprobe redistribution and source notice",
    "",
    `EDMG Studio includes unmodified FFmpeg and FFprobe executables from ${asset.sourceRepository}.`,
    `License: ${notice.licenseName}`,
    `License text: ${notice.licenseOutputName} (copied byte-for-byte from ${notice.licenseArchiveName} in the verified archive)`,
    "",
    `FFmpeg source commit: ${notice.ffmpegSource.commit}`,
    `FFmpeg source: ${notice.ffmpegSource.url}`,
    `Binary build source commit: ${notice.buildSource.commit}`,
    `Binary build source: ${notice.buildSource.url}`,
    "",
    `Pinned binary release: ${asset.releaseTag}`,
    `Pinned binary archive: ${asset.archiveName}`,
    `Pinned binary archive size: ${asset.size} bytes`,
    `Pinned binary archive SHA-256: ${asset.sha256}`,
    "",
    "The executable files are copied unchanged from that checksum-verified archive.",
    "",
  ].join("\n");
}

export function assertExpectedGplv3LicenseText(
  value,
  { archiveName = "pinned media archive", licenseFileName = "LICENSE.txt" } = {},
) {
  const text = String(value ?? "");
  if (!/GNU GENERAL PUBLIC LICENSE[\s\S]{0,200}Version 3/i.test(text)) {
    throw new Error(`${archiveName} contains an unexpected ${licenseFileName}; expected the GPLv3 license text`);
  }
  return text;
}

export function resolveMediaBuildCacheRoot({ root = studioRoot, env = process.env } = {}) {
  const configured = String(env.EDMG_STUDIO_BUILD_CACHE_ROOT ?? "").trim();
  return path.resolve(root, configured || ".cache");
}

async function sha256File(filePath) {
  const hash = crypto.createHash("sha256");
  const stream = fs.createReadStream(filePath);
  for await (const chunk of stream) hash.update(chunk);
  return hash.digest("hex");
}

export async function verifyPinnedArchive(filePath, asset) {
  let stat;
  try {
    stat = await fsp.stat(filePath);
  } catch (error) {
    if (error?.code === "ENOENT") return false;
    throw error;
  }
  if (!stat.isFile() || stat.size !== asset.size) return false;
  return (await sha256File(filePath)) === asset.sha256;
}

async function downloadPinnedArchive(asset, targetPath, fetchImpl) {
  const response = await fetchImpl(asset.url, {
    redirect: "follow",
    signal: AbortSignal.timeout(5 * 60 * 1000),
  });
  if (!response?.ok || !response.body) {
    throw new Error(`Download failed with HTTP ${response?.status ?? "unknown"}: ${asset.url}`);
  }
  await pipeline(Readable.fromWeb(response.body), fs.createWriteStream(targetPath, { flags: "wx" }));
}

export async function ensureCachedArchive(
  asset,
  {
    cacheRoot = resolveMediaBuildCacheRoot(),
    fetchImpl = globalThis.fetch,
    retries = 3,
    log = (message) => console.log(`[media-tools] ${message}`),
  } = {},
) {
  if (typeof fetchImpl !== "function") throw new Error("A Fetch implementation is required to download media tools");
  const cacheDir = path.join(cacheRoot, "media-tools", asset.releaseTag);
  const archivePath = path.join(cacheDir, asset.archiveName);
  await fsp.mkdir(cacheDir, { recursive: true });

  if (await verifyPinnedArchive(archivePath, asset)) {
    log(`verified cached ${asset.archiveName}`);
    return archivePath;
  }
  if (fs.existsSync(archivePath)) {
    await fsp.rm(archivePath, { force: true });
  }

  let lastError = null;
  for (let attempt = 1; attempt <= retries; attempt += 1) {
    const partialPath = path.join(
      cacheDir,
      `.${asset.archiveName}.partial-${process.pid}-${Date.now()}-${attempt}`,
    );
    try {
      log(`downloading pinned ${asset.archiveName} (${attempt}/${retries})`);
      await downloadPinnedArchive(asset, partialPath, fetchImpl);
      if (!(await verifyPinnedArchive(partialPath, asset))) {
        throw new Error(`Checksum or size mismatch for ${asset.archiveName}`);
      }
      if (await verifyPinnedArchive(archivePath, asset)) {
        await fsp.rm(partialPath, { force: true });
        return archivePath;
      }
      await fsp.rm(archivePath, { force: true });
      await fsp.rename(partialPath, archivePath);
      log(`cached verified ${asset.archiveName}`);
      return archivePath;
    } catch (error) {
      lastError = error;
      await fsp.rm(partialPath, { force: true });
      if (attempt < retries) {
        await new Promise((resolve) => setTimeout(resolve, attempt * 500));
      }
    }
  }
  throw new Error(`Unable to cache pinned media tools: ${lastError?.message ?? "unknown download error"}`);
}

function runExtraction(command, args, { env = process.env } = {}) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    env,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    const detail = String(result.stderr || result.stdout || "").trim();
    throw new Error(
      `${command} failed to extract pinned media tools with exit code ${result.status}${detail ? `: ${detail}` : ""}`,
    );
  }
}

async function extractPinnedArchive(asset, archivePath, extractionDir, platform) {
  await fsp.mkdir(extractionDir, { recursive: true });
  if (asset.archiveFormat === "zip" && platform === "win32") {
    runExtraction("powershell", [
      "-NoProfile",
      "-NonInteractive",
      "-ExecutionPolicy",
      "Bypass",
      "-Command",
      "Expand-Archive -LiteralPath $env:EDMG_MEDIA_ARCHIVE -DestinationPath $env:EDMG_MEDIA_EXTRACT_DIR -Force",
    ], {
      env: {
        ...process.env,
        EDMG_MEDIA_ARCHIVE: archivePath,
        EDMG_MEDIA_EXTRACT_DIR: extractionDir,
      },
    });
    return;
  }
  if (asset.archiveFormat === "tar.xz" && platform === "linux") {
    runExtraction("tar", ["-xJf", archivePath, "-C", extractionDir]);
    return;
  }
  throw new Error(`Unsupported ${asset.archiveFormat} extraction on ${platform}`);
}

export async function findUniqueArchiveFile(directory, fileName, { caseInsensitive = false } = {}) {
  const matches = [];
  const expectedName = caseInsensitive ? fileName.toLowerCase() : fileName;
  const pending = [directory];
  while (pending.length) {
    const current = pending.pop();
    for (const entry of await fsp.readdir(current, { withFileTypes: true })) {
      const candidate = path.join(current, entry.name);
      if (entry.isDirectory()) pending.push(candidate);
      else if (
        entry.isFile() &&
        (caseInsensitive ? entry.name.toLowerCase() : entry.name) === expectedName
      ) matches.push(candidate);
    }
  }
  if (matches.length !== 1) {
    throw new Error(`Expected exactly one ${fileName} in pinned archive; found ${matches.length}`);
  }
  return matches[0];
}

function assertMediaToolLaunch(toolPath, toolName) {
  const result = spawnSync(toolPath, ["-version"], {
    encoding: "utf8",
    maxBuffer: 2 * 1024 * 1024,
    stdio: ["ignore", "pipe", "pipe"],
    timeout: 15000,
    windowsHide: true,
  });
  if (result.error) throw result.error;
  const output = `${result.stdout || ""}\n${result.stderr || ""}`;
  if (result.status !== 0 || !new RegExp(`^${toolName} version`, "im").test(output)) {
    throw new Error(`Staged ${toolName} failed its version probe: ${output.trim()}`);
  }
}

export async function stagePinnedMediaTools({
  root = studioRoot,
  outDir = path.join(root, "electron-resources", "bin"),
  cacheRoot = resolveMediaBuildCacheRoot({ root }),
  platform = process.platform,
  arch = process.arch,
  manifest = loadPinnedMediaManifest(),
  fetchImpl = globalThis.fetch,
  log = (message) => console.log(`[media-tools] ${message}`),
} = {}) {
  const asset = resolvePinnedMediaAsset({ platform, arch, manifest });
  const archivePath = await ensureCachedArchive(asset, { cacheRoot, fetchImpl, log });
  const extractionDir = path.join(
    cacheRoot,
    "media-tools",
    asset.releaseTag,
    `.extract-${asset.key}-${process.pid}-${Date.now()}`,
  );
  const pendingPaths = [];
  try {
    await extractPinnedArchive(asset, archivePath, extractionDir, platform);
    await fsp.mkdir(outDir, { recursive: true });
    const staged = {};
    for (const [toolName, fileName] of Object.entries(asset.binaryNames)) {
      const sourcePath = await findUniqueArchiveFile(extractionDir, fileName);
      const sourceStat = await fsp.stat(sourcePath);
      if (!sourceStat.isFile() || sourceStat.size <= 0) {
        throw new Error(`Pinned archive contains an empty ${fileName}`);
      }
      const extension = path.extname(fileName);
      const stem = extension ? fileName.slice(0, -extension.length) : fileName;
      const pendingPath = path.join(outDir, `.${stem}.staging-${process.pid}-${Date.now()}${extension}`);
      pendingPaths.push(pendingPath);
      await fsp.copyFile(sourcePath, pendingPath);
      if (platform === "linux") await fsp.chmod(pendingPath, 0o755);
      staged[toolName] = { fileName, pendingPath, destination: path.join(outDir, fileName) };
    }

    const licenseSourcePath = await findUniqueArchiveFile(
      extractionDir,
      asset.distributionNotice.licenseArchiveName,
      { caseInsensitive: true },
    );
    assertExpectedGplv3LicenseText(await fsp.readFile(licenseSourcePath, "utf8"), {
      archiveName: `Pinned archive ${asset.archiveName}`,
      licenseFileName: asset.distributionNotice.licenseArchiveName,
    });
    const licensePendingPath = path.join(
      outDir,
      `.${asset.distributionNotice.licenseOutputName}.staging-${process.pid}-${Date.now()}`,
    );
    pendingPaths.push(licensePendingPath);
    await fsp.copyFile(licenseSourcePath, licensePendingPath);
    staged.license = {
      pendingPath: licensePendingPath,
      destination: path.join(outDir, asset.distributionNotice.licenseOutputName),
    };

    const sourceNoticePendingPath = path.join(
      outDir,
      `.${asset.distributionNotice.sourceNoticeOutputName}.staging-${process.pid}-${Date.now()}`,
    );
    pendingPaths.push(sourceNoticePendingPath);
    await fsp.writeFile(sourceNoticePendingPath, renderMediaSourceNotice(asset), "utf8");
    staged.sourceNotice = {
      pendingPath: sourceNoticePendingPath,
      destination: path.join(outDir, asset.distributionNotice.sourceNoticeOutputName),
    };

    assertMediaToolLaunch(staged.ffmpeg.pendingPath, "ffmpeg");
    assertMediaToolLaunch(staged.ffprobe.pendingPath, "ffprobe");
    for (const entry of Object.values(staged)) {
      await fsp.rm(entry.destination, { force: true });
      await fsp.rename(entry.pendingPath, entry.destination);
    }
    log(`staged pinned FFmpeg, FFprobe, license, and source notice ${asset.ffmpegVersion} for ${asset.key}`);
    return {
      platform,
      arch,
      releaseTag: asset.releaseTag,
      ffmpegVersion: asset.ffmpegVersion,
      archive: archivePath,
      archiveSha256: asset.sha256,
      ffmpeg: staged.ffmpeg.destination,
      ffprobe: staged.ffprobe.destination,
      license: staged.license.destination,
      sourceNotice: staged.sourceNotice.destination,
    };
  } finally {
    for (const pendingPath of pendingPaths) await fsp.rm(pendingPath, { force: true });
    await fsp.rm(extractionDir, { recursive: true, force: true });
  }
}

function parseCliArgs(argv) {
  let outDir = path.join(studioRoot, "electron-resources", "bin");
  for (let index = 0; index < argv.length; index += 1) {
    const value = String(argv[index] ?? "");
    if (value === "--out-dir") {
      if (index + 1 >= argv.length) throw new Error("--out-dir requires a path");
      outDir = path.resolve(studioRoot, argv[index + 1]);
      index += 1;
      continue;
    }
    if (value.startsWith("--out-dir=")) {
      outDir = path.resolve(studioRoot, value.slice("--out-dir=".length));
      continue;
    }
    throw new Error(`Unknown stage-media-tools argument: ${value}`);
  }
  return { outDir };
}

async function main() {
  const { outDir } = parseCliArgs(process.argv.slice(2));
  const result = await stagePinnedMediaTools({ outDir });
  console.log(JSON.stringify({ ok: true, ...result }, null, 2));
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : "";
if (invokedPath === import.meta.url) {
  main().catch((error) => {
    console.error(`[media-tools] FAILED: ${error?.message ?? error}`);
    process.exitCode = 1;
  });
}
