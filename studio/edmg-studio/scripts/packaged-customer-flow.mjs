import assert from "node:assert/strict";
import fs from "node:fs";
import fsp from "node:fs/promises";
import http from "node:http";
import https from "node:https";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

import {
  buildHermeticPackagedProofEnv,
  resolveHermeticProofProfile,
} from "./packaged-proof-environment.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const DEFAULT_REQUEST_TIMEOUT_MS = Number(process.env.EDMG_STUDIO_PROOF_REQUEST_TIMEOUT_MS || (10 * 60 * 1000));
const DEFAULT_HEAVY_REQUEST_TIMEOUT_MS = Number(process.env.EDMG_STUDIO_PROOF_HEAVY_TIMEOUT_MS || (20 * 60 * 1000));

function log(message) {
  console.log(`[packaged-customer-flow] ${message}`);
}

function resolvePackagedApp() {
  const envPath = process.env.EDMG_STUDIO_PACKAGED_APP;
  if (envPath && fs.existsSync(envPath)) return envPath;
  const candidate = path.join(root, "dist", "win-unpacked", process.platform === "win32" ? "EDMG Studio.exe" : "EDMG Studio");
  return fs.existsSync(candidate) ? candidate : "";
}

function resolveAudioFixture() {
  const envPath = process.env.EDMG_STUDIO_AUDIO_FIXTURE;
  if (envPath && fs.existsSync(envPath)) return envPath;
  const candidate = path.resolve(root, "..", "..", "juce_example", "out", "build", "x64-Debug", "_deps", "juce-src", "examples", "Assets", "cassette_recorder.wav");
  return fs.existsSync(candidate) ? candidate : "";
}

async function createSyntheticAudioFixture(targetPath, {
  durationSeconds = 8,
  sampleRate = 44100,
  channels = 2,
  frequencyHz = 110,
  amplitude = 0.28,
} = {}) {
  const totalFrames = Math.max(1, Math.floor(durationSeconds * sampleRate));
  const bytesPerSample = 2;
  const blockAlign = channels * bytesPerSample;
  const byteRate = sampleRate * blockAlign;
  const dataSize = totalFrames * blockAlign;
  const buffer = Buffer.alloc(44 + dataSize);

  buffer.write("RIFF", 0);
  buffer.writeUInt32LE(36 + dataSize, 4);
  buffer.write("WAVE", 8);
  buffer.write("fmt ", 12);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(channels, 22);
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(byteRate, 28);
  buffer.writeUInt16LE(blockAlign, 32);
  buffer.writeUInt16LE(bytesPerSample * 8, 34);
  buffer.write("data", 36);
  buffer.writeUInt32LE(dataSize, 40);

  for (let frame = 0; frame < totalFrames; frame += 1) {
    const t = frame / sampleRate;
    const envelope = Math.min(1, frame / (sampleRate * 0.2), (totalFrames - frame) / (sampleRate * 0.2));
    const left = Math.sin(2 * Math.PI * frequencyHz * t) * amplitude * envelope;
    const right = Math.sin(2 * Math.PI * (frequencyHz * 1.5) * t) * amplitude * envelope;
    const samples = [left, right];
    for (let channel = 0; channel < channels; channel += 1) {
      const sample = samples[channel % samples.length];
      const clamped = Math.max(-1, Math.min(1, sample));
      buffer.writeInt16LE(Math.round(clamped * 32767), 44 + (frame * channels + channel) * bytesPerSample);
    }
  }

  await fsp.mkdir(path.dirname(targetPath), { recursive: true });
  await fsp.writeFile(targetPath, buffer);
  return targetPath;
}

async function ensureAudioFixture() {
  const existing = resolveAudioFixture();
  if (existing) return { audioFixture: existing, generated: false };

  const fixturePath = path.join(os.tmpdir(), "edmg-packaged-customer-flow.wav");
  await createSyntheticAudioFixture(fixturePath);
  return { audioFixture: fixturePath, generated: true };
}

function chooseHomeRoot() {
  const preferred = process.env.EDMG_STUDIO_PROOF_ROOT;
  if (preferred) return preferred;
  return os.tmpdir();
}

async function allocatePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.listen(0, "127.0.0.1", () => resolve());
    server.on("error", reject);
  });
  const address = server.address();
  server.close();
  if (!address || typeof address === "string") throw new Error("Unable to allocate backend port");
  return address.port;
}

async function stopExistingPackagedProcesses() {
  if (process.platform !== "win32") return;
  const appDir = path.join(root, "dist", "win-unpacked").replace(/'/g, "''");
  const command = `$ErrorActionPreference='SilentlyContinue'; $appDir='${appDir}'; Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($appDir, [System.StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }`;
  await new Promise((resolve, reject) => {
    const child = spawn("powershell", ["-NoProfile", "-Command", command], { stdio: "ignore" });
    child.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`Failed to stop stale packaged processes: ${code}`))));
    child.on("error", reject);
  });
  await new Promise((resolve) => setTimeout(resolve, 1500));
}

async function waitForHealth(baseUrl, timeoutMs = 120000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      return await requestJson(`${baseUrl}/health`);
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 750));
    }
  }
  throw new Error(`Backend never became healthy at ${baseUrl}`);
}

function resolveTimeoutMs(value, fallback = DEFAULT_REQUEST_TIMEOUT_MS) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

async function assertSameExistingPath(actual, expected, message) {
  const [actualRealPath, expectedRealPath] = await Promise.all([
    fsp.realpath(actual),
    fsp.realpath(expected),
  ]);
  const normalize = process.platform === "win32"
    ? (value) => value.toLowerCase()
    : (value) => value;
  assert.equal(normalize(actualRealPath), normalize(expectedRealPath), message);
}

async function requestJsonViaNode(url, init, timeoutMs) {
  const target = new URL(url);
  const transport = target.protocol === "https:" ? https : http;
  const body = typeof init.body === "string" || Buffer.isBuffer(init.body) ? init.body : null;
  const headers = {
    accept: "application/json",
    ...(init.headers || {}),
  };
  if (body && headers["content-length"] == null) {
    headers["content-length"] = Buffer.byteLength(body);
  }

  return new Promise((resolve, reject) => {
    const request = transport.request(
      target,
      {
        method: init.method || "GET",
        headers,
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("end", () => {
          clearTimeout(timer);
          const text = Buffer.concat(chunks).toString("utf8");
          let payload = null;
          if (text) {
            try {
              payload = JSON.parse(text);
            } catch {
              payload = { raw: text };
            }
          }
          if ((response.statusCode || 500) >= 400) {
            reject(new Error(`${init.method || "GET"} ${url} failed: ${response.statusCode} ${text}`));
            return;
          }
          resolve(payload);
        });
      },
    );

    const timer = setTimeout(() => {
      request.destroy(new Error(`${init.method || "GET"} ${url} timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    request.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });

    if (body) {
      request.write(body);
    }
    request.end();
  });
}

async function requestJson(url, init = {}) {
  const timeoutMs = resolveTimeoutMs(init.timeoutMs);
  if (!(init.body instanceof FormData)) {
    return requestJsonViaNode(url, init, timeoutMs);
  }
  const response = await fetch(url, {
    ...init,
    signal: AbortSignal.timeout(timeoutMs),
    headers: {
      accept: "application/json",
      ...(init.headers || {}),
    },
  });
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { raw: text };
    }
  }
  if (!response.ok) {
    throw new Error(`${init.method || "GET"} ${url} failed: ${response.status} ${text}`);
  }
  return payload;
}

async function postJson(url, body) {
  return requestJson(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function uploadAudio(url, audioPath) {
  const form = new FormData();
  const bytes = await fsp.readFile(audioPath);
  form.set("file", new Blob([bytes]), path.basename(audioPath));
  return requestJson(url, { method: "POST", body: form });
}

async function killProcessTree(child) {
  if (!child || child.exitCode !== null) return;
  if (process.platform === "win32") {
    await new Promise((resolve) => {
      const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
      killer.on("exit", () => resolve());
      killer.on("error", () => resolve());
    });
    return;
  }
  child.kill("SIGTERM");
}

async function main() {
  const appExe = resolvePackagedApp();
  assert.ok(appExe, "Packaged app not found. Run pnpm run dist:win first or set EDMG_STUDIO_PACKAGED_APP.");
  const { audioFixture, generated: generatedAudioFixture } = await ensureAudioFixture();
  assert.ok(audioFixture, "Audio fixture not found and synthetic fallback generation failed.");
  const audioBytes = (await fsp.stat(audioFixture)).size;
  const heavyRequestTimeoutMs = Math.max(
    DEFAULT_HEAVY_REQUEST_TIMEOUT_MS,
    Math.ceil(audioBytes / (1024 * 1024)) * 5000,
  );

  await stopExistingPackagedProcesses();

  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "").replace("T", "_");
  const homeRoot = chooseHomeRoot();
  const studioHome = path.join(homeRoot, `EDMG-Packaged-Proof-${stamp}`);
  const { appDataDir, localAppDataDir, bootstrapPath } = resolveHermeticProofProfile(studioHome);
  await fsp.mkdir(studioHome, { recursive: true });
  await fsp.mkdir(path.dirname(bootstrapPath), { recursive: true });
  await fsp.rm(bootstrapPath, { force: true });
  const testPage = path.join(studioHome, "blank.html");
  await fsp.writeFile(testPage, "<!doctype html><html><body>packaged customer flow</body></html>\n");
  const port = Number(process.env.EDMG_STUDIO_PROOF_PORT || (await allocatePort()));
  const baseUrl = `http://127.0.0.1:${port}`;

  log(`launching ${appExe}`);
  if (generatedAudioFixture) {
    log(`generated synthetic audio fixture at ${audioFixture}`);
  }
  log(`using heavy request timeout ${heavyRequestTimeoutMs}ms for ${path.basename(audioFixture)} (${audioBytes} bytes)`);
  const child = spawn(appExe, [], {
    cwd: path.dirname(appExe),
    env: buildHermeticPackagedProofEnv({ studioHome, port, testPage }),
    stdio: "ignore",
  });

  try {
    const health = await waitForHealth(baseUrl);
    const status = await requestJson(`${baseUrl}/v1/setup/status`);
    const config = await requestJson(`${baseUrl}/v1/config`);
    const created = await postJson(`${baseUrl}/v1/projects`, { name: "Packaged Customer Proof" });
    const projectId = created?.project?.id;
    assert.ok(projectId, "Project creation did not return an id");

    const upload = await uploadAudio(`${baseUrl}/v1/projects/${projectId}/assets/audio`, audioFixture);
    const analyze = await requestJson(`${baseUrl}/v1/projects/${projectId}/analyze_audio`, {
      method: "POST",
      timeoutMs: heavyRequestTimeoutMs,
    });
    const plan = await postJson(`${baseUrl}/v1/projects/${projectId}/plan?mode=local`, {
      title: "Packaged Customer Proof",
      style_prefs: "audio reactive neon performance visuals",
      num_variants: 1,
      max_scenes: 4,
    });
    const apply = await postJson(`${baseUrl}/v1/projects/${projectId}/timeline/apply_plan`, { variant_index: 0, overwrite: true });
    const validate = await requestJson(`${baseUrl}/v1/projects/${projectId}/pipeline/validate?variant_index=0&preset=fast&mode=auto&engine=auto`);
    const run = await requestJson(`${baseUrl}/v1/projects/${projectId}/pipeline/run?variant_index=0&preset=fast&mode=auto&engine=auto`, { method: "POST" });
    const targetJobId = run?.job?.id || run?.assemble_job?.id;
    assert.ok(targetJobId, `Pipeline run did not return a target job payload: ${JSON.stringify(run)}`);

    let job = null;
    const tickHistory = [];
    const tickDeadline = Date.now() + 6 * 60 * 1000;
    while (Date.now() < tickDeadline) {
      const tick = await requestJson(`${baseUrl}/v1/jobs/tick`, { method: "POST" });
      if (tick?.job) {
        tickHistory.push({ id: tick.job.id, status: tick.job.status, type: tick.job.type });
        if (tick.job.id === targetJobId) {
          job = tick.job;
          if (["succeeded", "failed", "canceled"].includes(String(job.status))) break;
        }
      }
      await new Promise((resolve) => setTimeout(resolve, 750));
    }
    const jobs = await requestJson(`${baseUrl}/v1/projects/${projectId}/jobs`);
    if (!job && Array.isArray(jobs?.jobs)) {
      job = jobs.jobs.find((entry) => entry.id === targetJobId) || null;
    }
    assert.ok(job, `Did not observe the packaged target job ${targetJobId} in tick responses or job list`);
    const outputs = await requestJson(`${baseUrl}/v1/projects/${projectId}/outputs`);
    const transcript = analyze?.analysis?.transcript;
    const comfyOk = Boolean(status?.comfyui?.ok);
    const usesInternalPipeline = Boolean(run?.job?.id);
    const expectedDataDir = path.join(studioHome, "data");
    const expectedModelsDir = path.join(studioHome, "models");
    const expectedExternalDir = path.join(studioHome, "external");
    const expectedLogsDir = path.join(studioHome, "logs");
    const expectedOllamaModelsDir = path.join(expectedModelsDir, "ollama");
    const summary = {
      ok: job.status === "succeeded",
      studioHome,
      appDataDir,
      localAppDataDir,
      bootstrapPath,
      bootstrapCreated: fs.existsSync(bootstrapPath),
      baseUrl,
      health,
      paths: {
        studioHome: config?.studio_home ?? null,
        dataDir: config?.data_dir ?? null,
        modelsDir: config?.models_dir ?? null,
        ollamaModelsDir: config?.ollama_models_dir ?? null,
        logsDir: config?.logs_dir ?? null,
        externalDir: config?.external_dir ?? null,
        expectedDataDir,
        expectedModelsDir,
        expectedOllamaModelsDir,
        expectedLogsDir,
        expectedExternalDir,
        dataDirExists: fs.existsSync(expectedDataDir),
        modelsDirExists: fs.existsSync(expectedModelsDir),
        ollamaModelsDirExists: fs.existsSync(expectedOllamaModelsDir),
        logsDirExists: fs.existsSync(expectedLogsDir),
        externalDirExists: fs.existsSync(expectedExternalDir),
      },
      setupStatus: {
        backendBundleOk: status?.backend_bundle?.ok,
        ffmpegOk: status?.ffmpeg?.ok,
        edmgAvailable: status?.edmg?.available,
        edmgInstallable: status?.edmg?.installable,
        edmgRepoRoot: status?.edmg?.repo_root ?? null,
        sevenZipOk: status?.sevenzip?.ok,
        sevenZipPath: status?.sevenzip?.path ?? null,
        ollamaOk: status?.ollama?.ok,
        ollamaManagedModelsDir: status?.ollama?.managed_models_dir ?? null,
        ollamaManagedLaunchScript: status?.ollama?.managed_launch_script ?? null,
        ollamaLaunchAvailable: status?.ollama?.launch_available ?? null,
        comfyOk: status?.comfyui?.ok,
      },
      projectId,
      uploadOk: Boolean(upload?.ok),
      analyzeKeys: Object.keys((analyze && typeof analyze === "object" ? analyze.analysis : {}) || {}),
      transcript: {
        available: Boolean(transcript && typeof transcript === "object"),
        error: transcript?.error ?? null,
        note: transcript?.note ?? null,
        textAvailable: typeof transcript?.text === "string",
      },
      variantCount: Array.isArray(plan?.variants) ? plan.variants.length : 0,
      trackCount: Array.isArray(apply?.timeline?.tracks) ? apply.timeline.tracks.length : 0,
      validate: {
        mode: validate?.recommended?.mode,
        engine: validate?.recommended?.engine,
        modelId: validate?.recommended?.model_id,
        reason: validate?.recommended?.reason,
        diagnostics: Array.isArray(validate?.recommended?.diagnostics) ? validate.recommended.diagnostics : [],
      },
      run: {
        pathType: usesInternalPipeline ? "internal_or_proxy" : "queued_comfy_pipeline",
        renderMode: run?.render_mode,
        selectedMode: run?.selected?.mode,
        selectedEngine: run?.selected?.engine,
        selectedModel: run?.selected?.model_id,
        preflightMode: run?.preflight?.mode,
        renderEnqueued: run?.render_enqueued ?? null,
        assembleJobId: run?.assemble_job?.id ?? null,
      },
      job: {
        id: job.id,
        status: job.status,
        type: job.type,
        error: job.error || null,
      },
      outputs: {
        videoCount: Array.isArray(outputs?.videos) ? outputs.videos.length : 0,
        latestMode: outputs?.latest_internal_render?.mode || null,
        latestVideo: outputs?.latest_internal_render?.video || null,
        activeInternalJobs: Array.isArray(outputs?.active_internal_jobs)
          ? outputs.active_internal_jobs.map((entry) => `${entry.id}:${entry.status}`)
          : [],
      },
      tickHistory,
      projectJobs: Array.isArray(jobs?.jobs)
        ? jobs.jobs.map((entry) => ({ id: entry.id, status: entry.status, type: entry.type, error: entry.error || null }))
        : [],
    };

    console.log(JSON.stringify(summary, null, 2));

    assert.equal(summary.setupStatus.backendBundleOk, true, "Packaged backend bundle should be available");
    assert.equal(summary.setupStatus.ffmpegOk, true, "Bundled FFmpeg should be available");
    assert.equal(summary.setupStatus.edmgAvailable, true, "Bundled EDMG Core should be available");
    await assertSameExistingPath(summary.paths.studioHome, studioHome, "Packaged config should report the requested Studio home");
    await assertSameExistingPath(summary.paths.dataDir, expectedDataDir, "Packaged config data_dir should live under Studio home");
    await assertSameExistingPath(summary.paths.modelsDir, expectedModelsDir, "Packaged config models_dir should live under Studio home");
    await assertSameExistingPath(summary.paths.ollamaModelsDir, expectedOllamaModelsDir, "Packaged config ollama_models_dir should live under Studio models");
    await assertSameExistingPath(summary.paths.logsDir, expectedLogsDir, "Packaged config logs_dir should live under Studio home");
    await assertSameExistingPath(summary.paths.externalDir, expectedExternalDir, "Packaged config external_dir should live under Studio home");
    await assertSameExistingPath(summary.setupStatus.ollamaManagedModelsDir, expectedOllamaModelsDir, "Setup status should expose the managed Ollama models root");
    assert.equal(summary.paths.dataDirExists, true, "Packaged run should create the Studio data root");
    assert.equal(summary.paths.modelsDirExists, true, "Packaged run should create the Studio models root");
    assert.equal(summary.paths.ollamaModelsDirExists, true, "Packaged run should create the Studio Ollama models root");
    assert.equal(summary.paths.logsDirExists, true, "Packaged run should create the Studio logs root");
    assert.equal(summary.paths.externalDirExists, true, "Packaged run should create the Studio external root");
    assert.equal(summary.transcript.available, true, "Packaged analysis should return a transcription result");
    assert.equal(summary.transcript.error, null, `Packaged transcription should not fail: ${summary.transcript.error}`);
    assert.equal(summary.transcript.textAvailable, true, "Packaged transcription should return text, even when no speech is detected");
    assert.equal(summary.variantCount > 0, true, "Expected at least one planned variant");
    assert.equal(summary.trackCount > 0, true, "Expected timeline tracks after apply");
    assert.equal(summary.job.status, "succeeded", "Packaged render job should succeed");
    assert.equal(summary.outputs.videoCount > 0, true, "Expected rendered videos in outputs");
    if (!comfyOk) {
      assert.equal(["proxy", "internal"].includes(String(summary.validate.mode)), true, `Expected internal fallback recommendation when ComfyUI is unavailable, got ${summary.validate.mode}`);
      if (summary.run.renderMode) {
        assert.equal(["proxy", "internal"].includes(String(summary.run.renderMode)), true, `Expected internal/proxy packaged render mode, got ${summary.run.renderMode}`);
      }
      if (summary.outputs.latestMode) {
        assert.equal(["proxy", "internal"].includes(String(summary.outputs.latestMode)), true, `Expected latest packaged fallback mode, got ${summary.outputs.latestMode}`);
      }
    } else {
      assert.equal(["stills", "motion"].includes(String(summary.validate.mode)), true, `Expected stills/motion recommendation when ComfyUI is available, got ${summary.validate.mode}`);
      assert.equal(Boolean(summary.run.assembleJobId), true, "ComfyUI path should return an assemble job id");
    }
  } finally {
    await killProcessTree(child);
    await stopExistingPackagedProcesses();
  }
}

main().catch((error) => {
  console.error("[packaged-customer-flow] FAILED", error);
  process.exit(1);
});
