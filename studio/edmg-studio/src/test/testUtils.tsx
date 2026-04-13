import React from "react";
import { render } from "@testing-library/react";
import { vi } from "vitest";
import { UiModeProvider } from "../components/uiMode";
import { StudioSessionProvider } from "../components/studioSession";

type MockRouteHandler =
  | unknown
  | ((path: string, init?: RequestInit) => unknown | Promise<unknown>);

type MockRouteMap = Record<string, MockRouteHandler>;

function normalizePath(input: string | URL) {
  const raw = String(input);
  return raw.replace(/^https?:\/\/[^/]+/i, "");
}

function findRouteKey(routes: MockRouteMap, method: string, path: string) {
  const exactKeys = [`${method} ${path}`, path];
  for (const key of exactKeys) {
    if (key in routes) return key;
  }
  for (const key of Object.keys(routes)) {
    if (!key.endsWith("*")) continue;
    const prefix = key.slice(0, -1);
    if (path.startsWith(prefix)) return key;
    if (`${method} ${path}`.startsWith(prefix)) return key;
  }
  return "";
}

export function installEdmgBridge(overrides: Partial<NonNullable<Window["edmg"]>> = {}) {
  window.__EDMG_BACKEND_URL__ = "http://127.0.0.1:7863";
  window.edmg = {
    backendUrl: () => "http://127.0.0.1:7863",
    getBackendUrl: async () => "http://127.0.0.1:7863",
    revealPath: async (value: string) => ({ ok: true, action: "reveal_path", path: value }),
    showItemInFolder: async (value: string) => ({ ok: true, action: "show_item", path: value }),
    openPath: async (value: string) => ({ ok: true, action: "open_path", path: value }),
    openExternal: async () => {},
    getStudioPaths: async () => ({
      ok: true,
      platform: "win32",
      studioHome: "D:\\EDMG-Studio",
      dataDir: "D:\\EDMG-Studio\\data",
      modelsDir: "D:\\EDMG-Studio\\models",
      cacheRoot: "D:\\EDMG-Studio\\cache",
      logsDir: "D:\\EDMG-Studio\\logs",
      externalDir: "D:\\EDMG-Studio\\external",
      electronUserData: "D:\\EDMG-Studio\\electron",
      sessionData: "D:\\EDMG-Studio\\electron\\session",
      bootstrapConfigPath: "C:\\Users\\Tyler\\AppData\\Roaming\\EDMG Studio\\bootstrap.json",
      source: "test",
    }),
    relaunch: async () => ({ ok: true }),
    ...overrides,
  };
}

export function installFetchMock(routes: MockRouteMap) {
  const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const method = String(init?.method || "GET").toUpperCase();
    const path = normalizePath(input instanceof Request ? input.url : input);
    const key = findRouteKey(routes, method, path);
    if (!key) {
      throw new Error(`Unhandled fetch route: ${method} ${path}`);
    }
    const handler = routes[key];
    const payload = typeof handler === "function"
      ? await handler(path, init)
      : handler;
    return {
      ok: true,
      status: 200,
      json: async () => payload,
      text: async () => JSON.stringify(payload),
    } as Response;
  });

  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export function renderWithStudio(ui: React.ReactElement) {
  return render(
    <StudioSessionProvider>
      <UiModeProvider>{ui}</UiModeProvider>
    </StudioSessionProvider>,
  );
}
