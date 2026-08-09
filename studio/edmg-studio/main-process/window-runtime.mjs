import path from "node:path";
import { promises as fsp } from "node:fs";
import { pathToFileURL } from "node:url";
import { canNavigateWithinApp, normalizeExternalUrl } from "./security.mjs";

export const PRODUCTION_UI_LANDMARKS = Object.freeze([
  "Workspace",
  "Render",
  "Models",
  "Settings",
  "Setup",
]);

const PRODUCTION_UI_PROBE_TIMEOUT_MS = 10_000;
const PRODUCTION_UI_PROBE_INTERVAL_MS = 100;
const TEST_REPORT_BODY_TEXT_LIMIT = 8_000;

export function resolveWindowBackendUrl(backendUrl, getBackendUrl) {
  if (typeof getBackendUrl === "function") {
    const current = String(getBackendUrl() || "").trim();
    if (current) return current;
  }
  return String(backendUrl || "").trim();
}

export function createWindowRuntime({
  app,
  BrowserWindow,
  shell,
  rootDir,
  appName,
  isDev,
  devServerUrl,
  backendHost,
  backendPort,
  backendUrl,
  getBackendUrl,
  testMode,
  testPage,
  testReportPath,
  testProbeRevealPath,
  testProbeOpenPath,
  testExpectBackendUrl,
  pathExistsSync,
  ensureDirSync,
  appendTestTrace,
}) {
  let mainWindow = null;

  function getMainWindow() {
    return mainWindow;
  }

  function getPreloadPath() {
    return path.join(rootDir, "preload.cjs");
  }

  function getProdIndexPath() {
    return path.join(app.getAppPath(), "dist-web", "index.html");
  }

  function getWindowIconPath() {
    const candidates = app.isPackaged
      ? [
          path.join(process.resourcesPath, "app-icon.ico"),
          path.join(process.resourcesPath, "app-icon.png"),
          path.join(process.resourcesPath, "electron-resources", "app-icon.ico"),
          path.join(process.resourcesPath, "electron-resources", "app-icon.png"),
        ]
      : [
          path.join(rootDir, "electron-resources", "app-icon.ico"),
          path.join(rootDir, "electron-resources", "app-icon.png"),
        ];

    for (const candidate of candidates) {
      if (pathExistsSync(candidate)) {
        return candidate;
      }
    }

    return undefined;
  }

  async function loadRenderer(win) {
    if (testMode && testPage) {
      await win.loadURL(pathToFileURL(testPage).toString());
      return;
    }

    if (testMode && testReportPath) {
      await win.loadFile(getProdIndexPath());
      return;
    }

    if (isDev) {
      await win.loadURL(devServerUrl);
      return;
    }

    await win.loadFile(getProdIndexPath());
  }

  async function writeTestReport(payload) {
    if (!testMode || !testReportPath) {
      return { ok: false, skipped: true };
    }

    appendTestTrace(`writeTestReport ${JSON.stringify(payload)}`);
    await fsp.mkdir(path.dirname(testReportPath), { recursive: true });
    await fsp.writeFile(testReportPath, JSON.stringify(payload, null, 2), "utf8");

    return {
      ok: true,
      path: testReportPath,
    };
  }

  async function runWindowTestProbe(win) {
    if (!testMode || !testReportPath) return;

    const probeSource = JSON.stringify({
      revealPath: testProbeRevealPath || "",
      openPath: testProbeOpenPath || "",
      expectedBackendUrl: testExpectBackendUrl || "",
      expectProductionUi: !testPage,
      uiLandmarks: PRODUCTION_UI_LANDMARKS,
      productionUiTimeoutMs: PRODUCTION_UI_PROBE_TIMEOUT_MS,
      productionUiPollIntervalMs: PRODUCTION_UI_PROBE_INTERVAL_MS,
      bodyTextLimit: TEST_REPORT_BODY_TEXT_LIMIT,
    });

    try {
      appendTestTrace("runWindowTestProbe:executeJavaScript:start");
      const payload = await win.webContents.executeJavaScript(
        `(async () => {
          const probe = ${probeSource};
          const out = {
            ok: false,
            bridgeAvailable: !!window.edmg,
            testBridgeAvailable: !!window.__edmgTest,
            backendUrlSync: null,
            backendUrlAsync: null,
            reveal: null,
            open: null,
            expectProductionUi: !!probe.expectProductionUi,
            rendererUrl: "",
            rendererProtocol: "",
            documentTitle: "",
            bodyText: "",
            uiLandmarks: {
              expected: [...probe.uiLandmarks],
              found: [],
              missing: [...probe.uiLandmarks],
            },
            errors: [],
          };

          const normalizeText = (value) => String(value || "").replace(/\\s+/g, " ").trim();
          const delay = (durationMs) => new Promise((resolve) => window.setTimeout(resolve, durationMs));

          const captureRenderer = () => {
            if (probe.expectProductionUi) {
              for (const group of document.querySelectorAll("details.sidebar-group")) {
                group.open = true;
              }
            }

            const bodyText = normalizeText(document.body?.innerText || document.body?.textContent || "");
            const navLabels = Array.from(document.querySelectorAll(".sidebar-navText"))
              .map((element) => normalizeText(element.textContent));
            const found = probe.uiLandmarks.filter((landmark) => navLabels.includes(landmark));
            let protocol = "";
            try {
              protocol = new URL(window.location.href).protocol;
            } catch {
              protocol = "";
            }

            out.rendererUrl = String(window.location.href || "");
            out.rendererProtocol = protocol;
            out.documentTitle = normalizeText(document.title);
            out.bodyText = bodyText.slice(0, probe.bodyTextLimit);
            out.uiLandmarks = {
              expected: [...probe.uiLandmarks],
              found,
              missing: probe.uiLandmarks.filter((landmark) => !found.includes(landmark)),
            };
          };

          const productionUiIsReady = () => Boolean(
            out.rendererProtocol === "file:" &&
            out.bodyText.length > 0 &&
            out.uiLandmarks.missing.length === 0
          );

          try {
            out.backendUrlSync = typeof window.edmg?.backendUrl === "function" ? window.edmg.backendUrl() : null;
            out.backendUrlAsync = typeof window.edmg?.getBackendUrl === "function" ? await window.edmg.getBackendUrl() : null;
            if (probe.revealPath && typeof window.edmg?.revealPath === "function") {
              out.reveal = await window.edmg.revealPath(probe.revealPath);
            }
            if (probe.openPath && typeof window.edmg?.openPath === "function") {
              out.open = await window.edmg.openPath(probe.openPath);
            }

            const deadline = Date.now() + probe.productionUiTimeoutMs;
            do {
              captureRenderer();
              if (!probe.expectProductionUi || productionUiIsReady() || Date.now() >= deadline) {
                break;
              }
              await delay(probe.productionUiPollIntervalMs);
            } while (true);
          } catch (error) {
            out.errors.push(String(error && error.message ? error.message : error));
          }

          const backendMatches = !probe.expectedBackendUrl ||
            (out.backendUrlSync === probe.expectedBackendUrl && out.backendUrlAsync === probe.expectedBackendUrl);
          const revealMatches = !probe.revealPath || !!out.reveal?.ok;
          const openMatches = !probe.openPath || !!out.open?.ok;
          const productionUiMatches = !probe.expectProductionUi || productionUiIsReady();
          out.ok = Boolean(
            out.bridgeAvailable &&
            out.testBridgeAvailable &&
            backendMatches &&
            revealMatches &&
            openMatches &&
            productionUiMatches &&
            out.errors.length === 0
          );
          return out;
        })()`,
        true,
      );
      appendTestTrace(`runWindowTestProbe:executeJavaScript:done ${JSON.stringify(payload)}`);
      await writeTestReport(payload);
    } catch (error) {
      appendTestTrace(`runWindowTestProbe:error ${String(error?.message ?? error)}`);
      await writeTestReport({
        ok: false,
        bridgeAvailable: false,
        testBridgeAvailable: false,
        backendUrlSync: null,
        backendUrlAsync: null,
        reveal: null,
        open: null,
        expectProductionUi: !testPage,
        rendererUrl: "",
        rendererProtocol: "",
        documentTitle: "",
        bodyText: "",
        uiLandmarks: {
          expected: [...PRODUCTION_UI_LANDMARKS],
          found: [],
          missing: [...PRODUCTION_UI_LANDMARKS],
        },
        errors: [String(error?.message ?? error)],
      });
    }
  }

  function attachWindowDiagnostics(win) {
    win.webContents.on("did-fail-load", (_event, code, desc, url) => {
      console.error("[renderer] did-fail-load", { code, desc, url });
    });

    win.webContents.on("render-process-gone", (_event, details) => {
      console.error("[renderer] render-process-gone", details);
    });

    win.webContents.on("console-message", (details) => {
      console.log("[renderer console]", {
        level: details.level,
        message: details.message,
        line: details.lineNumber,
        sourceId: details.sourceId,
      });
    });
  }

  function attachWindowSecurityGuards(win) {
    win.webContents.setWindowOpenHandler(({ url }) => {
      const externalUrl = normalizeExternalUrl(url);
      if (externalUrl) {
        void shell.openExternal(externalUrl).catch((error) => {
          console.error("[window] failed to open external URL", externalUrl, error);
        });
        return { action: "deny" };
      }

      if (canNavigateWithinApp(url, win.webContents.getURL(), { testMode })) {
        return { action: "allow" };
      }

      return { action: "deny" };
    });

    win.webContents.on("will-navigate", (event, url) => {
      if (!canNavigateWithinApp(url, win.webContents.getURL(), { testMode })) {
        event.preventDefault();
      }
    });
  }

  async function createMainWindow() {
    const currentBackendUrl = resolveWindowBackendUrl(backendUrl, getBackendUrl);
    const win = new BrowserWindow({
      width: 1440,
      height: 920,
      minWidth: 1100,
      minHeight: 720,
      title: appName,
      icon: getWindowIconPath(),
      backgroundColor: "#05070b",
      show: false,
      autoHideMenuBar: false,
      webPreferences: {
        preload: getPreloadPath(),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: false,
        devTools: true,
        additionalArguments: [
          `--edmg-backend-host=${backendHost}`,
          `--edmg-backend-port=${String(backendPort)}`,
          ...(currentBackendUrl ? [`--edmg-backend-url=${currentBackendUrl}`] : []),
          `--edmg-test-mode=${testMode ? "1" : "0"}`,
        ],
      },
    });

    attachWindowDiagnostics(win);
    attachWindowSecurityGuards(win);

    if (testMode) {
      appendTestTrace("createMainWindow:created");
      win.webContents.on("did-finish-load", () => {
        appendTestTrace(`createMainWindow:did-finish-load ${win.webContents.getURL()}`);
        console.log("[test-mode] did-finish-load", win.webContents.getURL());
      });
    }

    win.once("ready-to-show", () => {
      win.show();
    });

    win.on("closed", () => {
      if (mainWindow === win) {
        mainWindow = null;
      }
    });

    if (testMode) {
      appendTestTrace("createMainWindow:loadRenderer:start");
      console.log("[test-mode] loading renderer");
    }
    await loadRenderer(win);
    if (testMode) {
      appendTestTrace(`createMainWindow:loadRenderer:done ${win.webContents.getURL()}`);
      console.log("[test-mode] renderer loaded", win.webContents.getURL());
      appendTestTrace("createMainWindow:runWindowTestProbe:start");
      console.log("[test-mode] running window test probe");
    }
    await runWindowTestProbe(win);
    if (testMode) {
      appendTestTrace("createMainWindow:runWindowTestProbe:done");
      console.log("[test-mode] window test probe finished");
    }

    mainWindow = win;
    return win;
  }

  return {
    getMainWindow,
    createMainWindow,
    writeTestReport,
  };
}
