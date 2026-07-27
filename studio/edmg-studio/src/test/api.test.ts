import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  apiGet,
  apiFetch,
  buildProjectFileUrl,
  ensureBrowserBridge,
  getBackendUrl,
  getBackendUrlAsync,
  setBackendAuthTokenForSession,
} from "../components/api";

const FRESH_TUNNEL = "https://equity-kilometers-periodically-floating.trycloudflare.com";
const DEAD_TUNNEL = "https://bridges-apartments-theoretical-value.trycloudflare.com";

describe("backend URL resolution", () => {
  beforeEach(() => {
    setBackendAuthTokenForSession("");
  });

  afterEach(() => {
    setBackendAuthTokenForSession("");
    vi.useRealTimers();
  });

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

  it("persists a resolved backend URL when localStorage is empty", () => {
    window.localStorage.removeItem("edmg.backendUrl");
    window.__EDMG_BACKEND_URL__ = `${FRESH_TUNNEL}/v1`;

    expect(getBackendUrl()).toBe(FRESH_TUNNEL);
    expect(window.localStorage.getItem("edmg.backendUrl")).toBe(FRESH_TUNNEL);
  });

  it("attaches the in-memory backend bearer token without writing it to storage", async () => {
    window.__EDMG_BACKEND_URL__ = FRESH_TUNNEL;
    setBackendAuthTokenForSession("secret-test-token");
    const fetchMock = vi.fn(async (_input: string | URL | Request, _init?: RequestInit) => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    } as Response));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiGet("/v1/config")).resolves.toEqual({ ok: true });

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer secret-test-token");
    expect(window.localStorage.getItem("edmg.backendAuthToken")).toBeNull();
  });

  it("refuses to send backend credentials to another origin", async () => {
    window.__EDMG_BACKEND_URL__ = FRESH_TUNNEL;
    setBackendAuthTokenForSession("secret-test-token");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiFetch("https://attacker.example/v1/config")).rejects.toThrow(
      "different origin",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("aborts a request at the configured timeout", async () => {
    vi.useFakeTimers();
    window.__EDMG_BACKEND_URL__ = FRESH_TUNNEL;
    const fetchMock = vi.fn((_input: string | URL | Request, init?: RequestInit) => (
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        }, { once: true });
      })
    ));
    vi.stubGlobal("fetch", fetchMock);

    const request = apiGet("/v1/setup/tasks", { timeoutMs: 250 });
    const rejection = expect(request).rejects.toThrow("timed out after 250 ms");
    await vi.advanceTimersByTimeAsync(250);
    await rejection;
  });

  it("forwards a caller AbortSignal without waiting for a timeout", async () => {
    window.__EDMG_BACKEND_URL__ = FRESH_TUNNEL;
    const fetchMock = vi.fn((_input: string | URL | Request, init?: RequestInit) => (
      new Promise<Response>((_resolve, reject) => {
        if (init?.signal?.aborted) {
          reject(new DOMException("Aborted", "AbortError"));
          return;
        }
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        }, { once: true });
      })
    ));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    const request = apiGet("/v1/setup/tasks", { signal: controller.signal });
    controller.abort();

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
    expect((fetchMock.mock.calls[0]?.[1] as RequestInit).signal?.aborted).toBe(true);
  });

  it("builds encoded project file URLs from validated backend and project paths", () => {
    const url = new URL(buildProjectFileUrl(FRESH_TUNNEL, "project_01", "outputs/videos/hero clip.mp4"));
    expect(url.origin).toBe(FRESH_TUNNEL);
    expect(url.pathname).toBe("/v1/projects/project_01/file");
    expect(url.searchParams.get("path")).toBe("outputs/videos/hero clip.mp4");
  });

  it("rejects unsafe project identifiers and traversal paths", () => {
    expect(() => buildProjectFileUrl(FRESH_TUNNEL, "../outside", "outputs/video.mp4")).toThrow(
      "Invalid project identifier",
    );
    expect(() => buildProjectFileUrl(FRESH_TUNNEL, "project_01", "../outside.mp4")).toThrow(
      "Invalid project-relative file path",
    );
    expect(() => buildProjectFileUrl("javascript:alert(1)", "project_01", "outputs/video.mp4")).toThrow(
      "valid HTTP(S) backend URL",
    );
  });
});
