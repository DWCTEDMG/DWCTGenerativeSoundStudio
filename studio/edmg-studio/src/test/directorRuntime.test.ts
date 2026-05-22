import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { describe, expect, it } from "vitest";
import { createDirectorRuntime } from "../../main-process/director-runtime.mjs";

function makeRuntime(spawnProcess: (...args: any[]) => any) {
  return createDirectorRuntime({
    app: {
      isPackaged: false,
      getPath: () => "C:\\DWCTGenerativeSoundStudio\\studio\\edmg-studio\\logs",
    },
    rootDir: "C:\\DWCTGenerativeSoundStudio\\studio\\edmg-studio",
    isWindows: true,
    directorHost: "127.0.0.1",
    directorPort: 39999,
    directorPublicBaseUrl: "http://127.0.0.1:39999",
    directorReadyTimeoutMs: 1,
    spawnDirector: true,
    pathExistsSync: () => true,
    ensureDirSync: () => {},
    safeStreamWrite: () => true,
    getStudioPaths: () => ({
      logsDir: "C:\\DWCTGenerativeSoundStudio\\studio\\edmg-studio\\logs",
    }),
    getBackendUrl: () => "http://127.0.0.1:7863",
    spawnProcess,
  });
}

describe("director runtime", () => {
  it("launches the Windows dev pnpm command through cmd.exe", async () => {
    let spawnCommand = "";
    let spawnArgs: string[] = [];
    let spawnOptions: any = null;
    const fakeSpawn = (command: string, args: string[], options: any) => {
      spawnCommand = command;
      spawnArgs = args;
      spawnOptions = options;
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
      return child;
    };

    const runtime = makeRuntime(fakeSpawn);

    await expect(runtime.startDirectorIfNeeded()).resolves.toBe(false);
    expect(spawnCommand.toLowerCase()).toContain("cmd");
    expect(spawnArgs.join(" ")).toContain("pnpm.cmd start");
    expect(spawnOptions?.shell).toBe(false);
  });
});
