import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { assertPinnedUvVersion } from "./release-python-toolchain.mjs";
import { RELEASE_ARTIFACT_SETS, writeReleaseEvidence } from "./release-evidence-lib.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");

function parseArgs(argv) {
  let phase = "bundle";
  let profile = "";
  let artifactSet = "";
  let reuseExistingSbom;
  for (let index = 0; index < argv.length; index += 1) {
    const arg = String(argv[index] ?? "");
    if (arg === "--phase") {
      phase = String(argv[index + 1] ?? "").trim() || phase;
      index += 1;
      continue;
    }
    if (arg.startsWith("--phase=")) {
      phase = arg.slice("--phase=".length).trim() || phase;
      continue;
    }
    if (arg === "--profile") {
      profile = String(argv[index + 1] ?? "").trim();
      index += 1;
      continue;
    }
    if (arg.startsWith("--profile=")) {
      profile = arg.slice("--profile=".length).trim();
      continue;
    }
    if (arg === "--artifact-set") {
      artifactSet = String(argv[index + 1] ?? "").trim();
      index += 1;
      continue;
    }
    if (arg.startsWith("--artifact-set=")) {
      artifactSet = arg.slice("--artifact-set=".length).trim();
      continue;
    }
    if (arg === "--reuse-existing-sbom") {
      reuseExistingSbom = true;
      continue;
    }
    throw new Error(`Unknown generate-release-evidence argument: ${arg}`);
  }
  if (!["bundle", "dist"].includes(phase)) {
    throw new Error(`Invalid --phase ${JSON.stringify(phase)}. Expected bundle or dist.`);
  }
  if (phase === "dist" && !RELEASE_ARTIFACT_SETS.includes(artifactSet)) {
    throw new Error(
      `--artifact-set is required for ${phase} evidence (${RELEASE_ARTIFACT_SETS.join(", ")})`,
    );
  }
  if (phase === "bundle" && artifactSet) {
    throw new Error("--artifact-set is only valid for dist evidence");
  }
  if (reuseExistingSbom === true && phase !== "bundle") {
    throw new Error("--reuse-existing-sbom is only valid for bundle evidence repair");
  }
  return { phase, profile, artifactSet, reuseExistingSbom };
}

function resolveUv() {
  const uvCommand = String(process.env.EDMG_UV || "uv").trim();
  if (!uvCommand) throw new Error("EDMG_UV must not be empty");
  const result = spawnSync(uvCommand, ["--version"], {
    cwd: path.join(root, "python_backend"),
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    shell: false,
  });
  if (result.error) throw new Error(`Could not query uv version: ${result.error.message}`);
  if (result.status !== 0) throw new Error(`Could not query uv version (exit ${result.status ?? "unknown"})`);
  assertPinnedUvVersion(String(result.stdout || "").trim());
  return uvCommand;
}

async function main() {
  const { phase, profile, artifactSet, reuseExistingSbom } = parseArgs(process.argv.slice(2));
  const packageJson = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
  const uvCommand = resolveUv();
  const evidence = await writeReleaseEvidence({
    root,
    phase,
    profile,
    artifactSet,
    uvCommand,
    version: String(packageJson.version || ""),
    env: process.env,
    reuseExistingSbom,
  });
  console.log(
    JSON.stringify(
      {
        ok: true,
        phase,
        artifactSet: artifactSet || undefined,
        evidenceDir: path.relative(root, evidence.evidenceDir).split(path.sep).join("/"),
        indexPath: path.relative(root, evidence.indexPath).split(path.sep).join("/"),
        checksumPath: path.relative(root, evidence.checksumPath).split(path.sep).join("/"),
        sbomPath: path.relative(root, evidence.sbomPath).split(path.sep).join("/"),
        artifactCount: evidence.checksumManifest.artifacts.length,
        codeSigning: evidence.checksumManifest.codeSigning,
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error("[generate-release-evidence] FAILED", error);
  process.exit(1);
});
