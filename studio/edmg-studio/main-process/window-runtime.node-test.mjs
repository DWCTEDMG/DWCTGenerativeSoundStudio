import assert from "node:assert/strict";
import test from "node:test";

import {
  assertTrustedRendererIpc,
  canNavigateWithinApp,
  normalizeExternalUrl,
} from "./security.mjs";
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
      this.webContents = { on: () => {}, setWindowOpenHandler: () => {} };
    }

    once() {}
    on() {}
    show() {}
    async loadFile() {}
  }

  const runtime = createWindowRuntime({
    app: { isPackaged: false, getAppPath: () => "E:\\studio" },
    BrowserWindow: FakeBrowserWindow,
    shell: { openExternal: async () => {} },
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

test("security helpers normalize and gate external navigation", () => {
  assert.equal(
    normalizeExternalUrl("https://example.com/path///?q=1#frag"),
    "https://example.com/path?q=1#frag",
  );
  assert.equal(normalizeExternalUrl("javascript:alert(1)"), "");
  assert.equal(
    canNavigateWithinApp("https://example.com/dashboard", "https://example.com/library", {
      testMode: false,
    }),
    true,
  );
  assert.equal(
    canNavigateWithinApp("https://example.com/dashboard", "https://other.example/library", {
      testMode: false,
    }),
    false,
  );

  assert.equal(
    assertTrustedRendererIpc(
      {
        senderFrame: { url: "http://127.0.0.1:5173" },
        sender: { getURL: () => "" },
      },
      "edmg:test",
      { devServerUrl: "http://127.0.0.1:5173" },
    ),
    "http://127.0.0.1:5173",
  );
  assert.throws(
    () =>
      assertTrustedRendererIpc(
        {
          senderFrame: { url: "https://attacker.example" },
          sender: { getURL: () => "" },
        },
        "edmg:test",
        { devServerUrl: "http://127.0.0.1:5173" },
      ),
    /Blocked edmg:test/,
  );
});
