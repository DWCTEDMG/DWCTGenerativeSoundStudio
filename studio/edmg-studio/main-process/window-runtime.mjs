import path from "node:path";
import { promises as fsp } from "node:fs";
import { pathToFileURL } from "node:url";

export function createWindowRuntime({
  app,
  BrowserWindow,
  rootDir,
  appName,
  isDev,
  devServerUrl,
  backendHost,
  backendPort,
  backendUrl,
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
      await win.loadURL("data:text/html;charset=utf-8,%3C!doctype%20html%3E%3Chtml%3E%3Cbody%3Eedmg%20test%20mode%3C%2Fbody%3E%3C%2Fhtml%3E");
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
            errors: [],
          };

          try {
            out.backendUrlSync = typeof window.edmg?.backendUrl === "function" ? window.edmg.backendUrl() : null;
            out.backendUrlAsync = typeof window.edmg?.getBackendUrl === "function" ? await window.edmg.getBackendUrl() : null;
            if (probe.revealPath && typeof window.edmg?.revealPath === "function") {
              out.reveal = await window.edmg.revealPath(probe.revealPath);
            }
            if (probe.openPath && typeof window.edmg?.openPath === "function") {
              out.open = await window.edmg.openPath(probe.openPath);
            }
          } catch (error) {
            out.errors.push(String(error && error.message ? error.message : error));
          }

          const backendMatches = !probe.expectedBackendUrl ||
            (out.backendUrlSync === probe.expectedBackendUrl && out.backendUrlAsync === probe.expectedBackendUrl);
          const revealMatches = !probe.revealPath || !!out.reveal?.ok;
          const openMatches = !probe.openPath || !!out.open?.ok;
          out.ok = Boolean(
            out.bridgeAvailable &&
            out.testBridgeAvailable &&
            backendMatches &&
            revealMatches &&
            openMatches &&
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

  async function createMainWindow() {
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
          ...(backendUrl ? [`--edmg-backend-url=${backendUrl}`] : []),
          `--edmg-test-mode=${testMode ? "1" : "0"}`,
        ],
      },
    });

    attachWindowDiagnostics(win);

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
