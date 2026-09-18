import type { ChildProcess } from "node:child_process";

type DirectorRuntimeOptions = {
  app: {
    isPackaged: boolean;
    getPath: (name: string) => string;
  };
  rootDir: string;
  isWindows: boolean;
  directorHost: string;
  directorPort: number;
  directorPublicBaseUrl: string;
  directorReadyTimeoutMs: number;
  spawnDirector: boolean;
  pathExistsSync: (path: string) => boolean;
  ensureDirSync: (path: string) => unknown;
  safeStreamWrite: (...args: unknown[]) => unknown;
  getStudioPaths: () => { logsDir?: string };
  getBackendUrl: () => string;
  spawnProcess?: (...args: any[]) => ChildProcess;
};

type DirectorStatus = {
  ok: true;
  available: boolean;
  managed: boolean;
  serviceUrl: string;
  mcpUrl: string;
  advertisedBaseUrl: string;
  backendUrl: string;
  pid: number | null;
  lastError: string;
  startedAt: string | null;
  packaged: boolean;
};

export function createDirectorRuntime(options: DirectorRuntimeOptions): {
  getCurrentDirectorUrl: () => string;
  getCurrentDirectorMcpUrl: () => string;
  startDirectorIfNeeded: () => Promise<boolean>;
  stopDirector: () => void;
  restartDirector: (options?: { directorPublicBaseUrl?: string }) => Promise<boolean>;
  getDirectorStatus: () => Promise<DirectorStatus>;
};
