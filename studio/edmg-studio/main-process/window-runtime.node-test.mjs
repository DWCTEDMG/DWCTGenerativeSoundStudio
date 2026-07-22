import assert from "node:assert/strict";
import test from "node:test";

import { createWindowRuntime, resolveWindowBackendUrl } from "./window-runtime.mjs";

test("window preload receives the backend URL selected during startup", () => {
  assert.equal(
    resolveWindowBackendUrl(
      "http://127.0.0.1:7863",
      () => "http://127.0.0.1:17863",
    ),
    "http://127.0.0.1:17863",
  );
});

test("window backend URL falls back to the configured endpoint", () => {
  assert.equal(
    resolveWindowBackendUrl("http://127.0.0.1:7863", () => ""),
    "http://127.0.0.1:7863",
  );
});

test("BrowserWindow preload arguments carry the backend URL selected after startup", async () => {
  let windowOptions = null;
  class FakeBrowserWindow {
    constructor(options) {
      windowOptions = options;
      this.webContents = { on: () => {} };
    }

    once() {}
    on() {}
    show() {}
    async loadFile() {}
  }

  const runtime = createWindowRuntime({
    app: { isPackaged: false, getAppPath: () => "E:\\studio" },
    BrowserWindow: FakeBrowserWindow,
    rootDir: "E:\\studio",
    appName: "EDMG Studio",
    isDev: false,
    devServerUrl: "",
    backendHost: "127.0.0.1",
    backendPort: 7863,
    backendUrl: "http://127.0.0.1:7863",
    getBackendUrl: () => "http://127.0.0.1:17863",
    testMode: false,
    pathExistsSync: () => false,
    ensureDirSync: () => {},
    appendTestTrace: () => {},
  });

  await runtime.createMainWindow();
  assert.ok(windowOptions);
  assert.ok(
    windowOptions.webPreferences.additionalArguments.includes(
      "--edmg-backend-url=http://127.0.0.1:17863",
    ),
  );
  assert.equal(
    windowOptions.webPreferences.additionalArguments.includes(
      "--edmg-backend-url=http://127.0.0.1:7863",
    ),
    false,
  );
});
