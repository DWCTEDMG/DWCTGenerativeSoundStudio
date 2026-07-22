import { EventEmitter } from "node:events";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { PassThrough } from "node:stream";
import { afterAll, describe, expect, it } from "vitest";
import { createDirectorRuntime } from "../../main-process/director-runtime.mjs";

const TEST_LOGS_DIR = mkdtempSync(path.join(tmpdir(), "edmg-director-runtime-"));

function makeRuntime(spawnProcess: (...args: any[]) => any) {
  return createDirectorRuntime({
    app: {
      isPackaged: false,
      getPath: () => TEST_LOGS_DIR,
    },
    rootDir: "C:\\DWCTGenerativeSoundStudio\\studio\\edmg-studio",
    isWindows: true,
    directorHost: "127.0.0.1",
    directorPort: 39999,
    directorPublicBaseUrl: "http://127.0.0.1:39999",
    directorReadyTimeoutMs: 1,
    spawnDirector: true,
    pathExistsSync: () => true,
    ensureDirSync: (directory: string) => mkdirSync(directory, { recursive: true }),
    safeStreamWrite: () => true,
    getStudioPaths: () => ({
      logsDir: TEST_LOGS_DIR,
    }),
    getBackendUrl: () => "http://127.0.0.1:7863",
    spawnProcess,
  });
}

afterAll(() => {
  rmSync(TEST_LOGS_DIR, { recursive: true, force: true });
});

describe("director runtime", () => {
  it("builds and launches the dev Director without invoking a command shell", async () => {
    const spawnCalls: Array<{ command: string; args: string[]; options: any }> = [];
    const fakeSpawn = (command: string, args: string[], options: any) => {
      spawnCalls.push({ command, args, options });
      const child = new EventEmitter() as EventEmitter & {
        pid: number;
        stdout: PassThrough;
        stderr: PassThrough;
        kill: () => void;
      };
      child.pid = 12345;
      child.stdout = new PassThrough();
      child.stderr = new PassThrough();
      child.kill = () => {};
      if (spawnCalls.length <= 2) {
        queueMicrotask(() => child.emit("exit", 0, null));
      }
      return child;
    };

    const runtime = makeRuntime(fakeSpawn);

    await expect(runtime.startDirectorIfNeeded()).resolves.toBe(false);
    expect(spawnCalls).toHaveLength(3);
    expect(spawnCalls[0]?.command).toBe(process.execPath);
    expect(spawnCalls[0]?.args.join(" ")).toContain("node_modules\\vite\\bin\\vite.js build");
    expect(spawnCalls[1]?.command).toBe(process.execPath);
    expect(spawnCalls[1]?.args.join(" ")).toContain("node_modules\\typescript\\bin\\tsc -p");
    expect(spawnCalls[2]?.command).toBe(process.execPath);
    expect(spawnCalls[2]?.args.join(" ")).toContain("dist-server\\server.js");
    expect(spawnCalls.every((call) => call.options?.shell === false)).toBe(true);
    expect(spawnCalls.every((call) => call.options?.env?.ELECTRON_RUN_AS_NODE === "1")).toBe(true);
  });
});
