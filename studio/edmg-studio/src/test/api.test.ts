import { describe, expect, it, vi } from "vitest";
import {
  ensureBrowserBridge,
  getBackendUrl,
  getBackendUrlAsync,
} from "../components/api";

const FRESH_TUNNEL = "https://equity-kilometers-periodically-floating.trycloudflare.com";
const DEAD_TUNNEL = "https://bridges-apartments-theoretical-value.trycloudflare.com";

describe("backend URL resolution", () => {
  it("prefers the live Electron bridge URL over stale browser storage", async () => {
    window.localStorage.setItem("edmg.backendUrl", DEAD_TUNNEL);
    window.__EDMG_BACKEND_URL__ = DEAD_TUNNEL;
    window.edmg = {
      backendUrl: () => FRESH_TUNNEL,
      getBackendUrl: vi.fn(async () => `${FRESH_TUNNEL}/v1`),
    };

    await expect(getBackendUrlAsync()).resolves.toBe(FRESH_TUNNEL);
    expect(getBackendUrl()).toBe(FRESH_TUNNEL);
    expect(window.localStorage.getItem("edmg.backendUrl")).toBe(FRESH_TUNNEL);
  });

  it("uses the runtime URL in browser fallback mode without recursive bridge calls", () => {
    window.localStorage.setItem("edmg.backendUrl", DEAD_TUNNEL);
    window.__EDMG_BACKEND_URL__ = `${FRESH_TUNNEL}/health`;

    ensureBrowserBridge();

    expect(window.edmg?.backendUrl()).toBe(FRESH_TUNNEL);
    expect(getBackendUrl()).toBe(FRESH_TUNNEL);
    expect(window.localStorage.getItem("edmg.backendUrl")).toBe(FRESH_TUNNEL);
  });
});
