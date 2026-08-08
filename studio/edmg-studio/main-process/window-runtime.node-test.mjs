import assert from "node:assert/strict";
import { promises as fsp } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";
import vm from "node:vm";

import {
  assertTrustedRendererIpc,
  canNavigateWithinApp,
  normalizeExternalUrl,
} from "./security.mjs";
import { createWindowRuntime, resolveWindowBackendUrl } from "./window-runtime.mjs";

function createProbeWindowClass({ probePayload, onProbe } = {}) {
  return class FakeProbeBrowserWindow {
    constructor() {
      this.currentUrl = "";
      this.loadedFile = "";
      this.loadedUrl = "";
      this.webContents = {
        on: () => {},
        setWindowOpenHandler: () => {},
        getURL: () => this.currentUrl,
        executeJavaScript: async (source) => {
          onProbe?.(source);
          return typeof probePayload === "function" ? probePayload(source) : probePayload;
        },
      };
      FakeProbeBrowserWindow.instance = this;
    }

    once() {}
    on() {}
    show() {}

    async loadFile(filePath) {
      this.loadedFile = filePath;
      this.currentUrl = pathToFileURL(filePath).toString();
    }

    async loadURL(url) {
      this.loadedUrl = url;
      this.currentUrl = url;
    }
  };
}

function evaluateProbeScript(source, { rendererUrl, documentTitle, bodyText, navLabels }) {
  const window = {
    edmg: {
      backendUrl: () => "http://127.0.0.1:7863",
      getBackendUrl: async () => "http://127.0.0.1:7863",
    },
    __edmgTest: {},
    location: { href: rendererUrl },
    setTimeout,
  };
  const document = {
    title: documentTitle,
    body: { innerText: bodyText, textContent: bodyText },
    querySelectorAll: (selector) => {
      if (selector === ".sidebar-navText") {
        return navLabels.map((label) => ({ textContent: label }));
      }
      return [];
    },
  };
  return vm.runInNewContext(source, { document, URL, window });
}

function createProbeRuntimeOptions({ BrowserWindow, appPath, reportPath, testPage }) {
  return {
    app: { isPackaged: false, getAppPath: () => appPath },
    BrowserWindow,
    shell: { openExternal: async () => {} },
    rootDir: appPath,
    appName: "EDMG Studio",
    isDev: true,
    devServerUrl: "http://127.0.0.1:5173",
    backendHost: "127.0.0.1",
    backendPort: 7863,
    backendUrl: "http://127.0.0.1:7863",
    getBackendUrl: () => "http://127.0.0.1:7863",
    testMode: true,
    testPage,
    testReportPath: reportPath,
    pathExistsSync: () => false,
    ensureDirSync: () => {},
    appendTestTrace: () => {},
  };
}

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

test("report-only test mode loads the production renderer and records the production UI contract", async (t) => {
  const tempRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-window-runtime-production-"));
  t.after(() => fsp.rm(tempRoot, { recursive: true, force: true }));

  const appPath = path.join(tempRoot, "app");
  const reportPath = path.join(tempRoot, "reports", "window.json");
  const expectedIndex = path.join(appPath, "dist-web", "index.html");
  const expectedPayload = {
    ok: true,
    bridgeAvailable: true,
    testBridgeAvailable: true,
    backendUrlSync: "http://127.0.0.1:7863",
    backendUrlAsync: "http://127.0.0.1:7863",
    reveal: null,
    open: null,
    expectProductionUi: true,
    rendererUrl: pathToFileURL(expectedIndex).toString(),
    rendererProtocol: "file:",
    documentTitle: "EDMG Studio",
    bodyText: "EDMG Studio Workspace Render Models Settings Setup",
    uiLandmarks: {
      expected: ["Workspace", "Render", "Models", "Settings", "Setup"],
      found: ["Workspace", "Render", "Models", "Settings", "Setup"],
      missing: [],
    },
    errors: [],
  };
  let probeScript = "";
  const FakeBrowserWindow = createProbeWindowClass({
    probePayload: (source) =>
      evaluateProbeScript(source, {
        rendererUrl: pathToFileURL(expectedIndex).toString(),
        documentTitle: "EDMG Studio",
        bodyText: "EDMG Studio Workspace Render Models Settings Setup",
        navLabels: ["Workspace", "Render", "Models", "Settings", "Setup"],
      }),
    onProbe: (source) => {
      probeScript = source;
    },
  });
  const runtime = createWindowRuntime(
    createProbeRuntimeOptions({ BrowserWindow: FakeBrowserWindow, appPath, reportPath }),
  );

  await runtime.createMainWindow();

  assert.equal(FakeBrowserWindow.instance.loadedFile, expectedIndex);
  assert.equal(FakeBrowserWindow.instance.loadedUrl, "");
  assert.doesNotThrow(() => new Function(`return ${probeScript};`));
  assert.equal(probeScript.includes('"expectProductionUi":true'), true);
  assert.equal(probeScript.includes('replace(/\\s+/g, " ")'), true);
  assert.match(probeScript, /out\.rendererProtocol === "file:"/);
  assert.deepEqual(JSON.parse(await fsp.readFile(reportPath, "utf8")), expectedPayload);
});

test("fixture test mode keeps loading the requested page without requiring production landmarks", async (t) => {
  const tempRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "edmg-window-runtime-fixture-"));
  t.after(() => fsp.rm(tempRoot, { recursive: true, force: true }));

  const appPath = path.join(tempRoot, "app");
  const reportPath = path.join(tempRoot, "reports", "window.json");
  const testPage = path.join(tempRoot, "fixture.html");
  const fixtureUrl = pathToFileURL(testPage).toString();
  const expectedPayload = {
    ok: true,
    bridgeAvailable: true,
    testBridgeAvailable: true,
    backendUrlSync: "http://127.0.0.1:7863",
    backendUrlAsync: "http://127.0.0.1:7863",
    reveal: null,
    open: null,
    expectProductionUi: false,
    rendererUrl: fixtureUrl,
    rendererProtocol: "file:",
    documentTitle: "Fixture",
    bodyText: "fixture",
    uiLandmarks: {
      expected: ["Workspace", "Render", "Models", "Settings", "Setup"],
      found: [],
      missing: ["Workspace", "Render", "Models", "Settings", "Setup"],
    },
    errors: [],
  };
  let probeScript = "";
  const FakeBrowserWindow = createProbeWindowClass({
    probePayload: (source) =>
      evaluateProbeScript(source, {
        rendererUrl: fixtureUrl,
        documentTitle: "Fixture",
        bodyText: "fixture",
        navLabels: [],
      }),
    onProbe: (source) => {
      probeScript = source;
    },
  });
  const runtime = createWindowRuntime(
    createProbeRuntimeOptions({ BrowserWindow: FakeBrowserWindow, appPath, reportPath, testPage }),
  );

  await runtime.createMainWindow();

  assert.equal(FakeBrowserWindow.instance.loadedUrl, fixtureUrl);
  assert.equal(FakeBrowserWindow.instance.loadedFile, "");
  assert.equal(probeScript.includes('"expectProductionUi":false'), true);
  assert.match(probeScript, /!probe\.expectProductionUi \|\| productionUiIsReady\(\)/);
  assert.deepEqual(JSON.parse(await fsp.readFile(reportPath, "utf8")), expectedPayload);
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
