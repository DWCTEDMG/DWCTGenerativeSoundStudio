import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import process from "node:process";

const root = path.resolve(import.meta.dirname, "..");
const output = path.join(root, "src", "shared", "api", "generated", "project-health.ts");
const temporaryDirectory = mkdtempSync(path.join(tmpdir(), "edmg-openapi-"));
const schemaPath = path.join(temporaryDirectory, "project-health.json");
const generatedPath = path.join(temporaryDirectory, "project-health.ts");
const check = process.argv.includes("--check");

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: root,
    encoding: "utf8",
    shell: false,
    ...options,
  });
  if (result.status !== 0) {
    process.stderr.write(result.stderr || result.stdout || `${command} failed\n`);
    process.exit(result.status ?? 1);
  }
  return result.stdout;
}

try {
  const schema = run("uv", [
    "run",
    "--project",
    "python_backend",
    "--frozen",
    "python",
    "python_backend/scripts/export_project_health_openapi.py",
  ]);
  await import("node:fs/promises").then(({ writeFile }) => writeFile(schemaPath, schema, "utf8"));
  const cli = path.join(root, "node_modules", "openapi-typescript", "bin", "cli.js");
  run(process.execPath, [cli, schemaPath, "-o", generatedPath]);
  const generated = readFileSync(generatedPath, "utf8").replaceAll(schemaPath.replaceAll("\\", "/"), "FastAPI Project Health OpenAPI");

  if (check) {
    let committed = "";
    try {
      committed = readFileSync(output, "utf8");
    } catch {
      // The diagnostic below also covers a missing generated file.
    }
    if (committed !== generated) {
      process.stderr.write("Generated API contracts are stale. Run `pnpm run generate:api-contracts`.\n");
      process.exit(1);
    }
  } else {
    await import("node:fs/promises").then(async ({ mkdir, writeFile }) => {
      await mkdir(path.dirname(output), { recursive: true });
      await writeFile(output, generated, "utf8");
    });
    process.stdout.write(`Generated ${path.relative(root, output)}\n`);
  }
} finally {
  rmSync(temporaryDirectory, { recursive: true, force: true });
}
