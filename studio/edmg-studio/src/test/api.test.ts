import { describe, expect, it, vi } from "vitest";

describe("frontend backend URL resolution", () => {
  it("prefers the NVIDIA/dev backend on port 8000 when it is healthy", async () => {
    const fetchMock = vi.fn(async (url: string) => ({
      ok: url === "http://127.0.0.1:8000/health",
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.resetModules();

    const { getBackendUrlAsync } = await import("../components/api");

    await expect(getBackendUrlAsync()).resolves.toBe("http://127.0.0.1:8000");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/health",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("falls back to the packaged desktop backend port when port 8000 is not healthy", async () => {
    const fetchMock = vi.fn(async (url: string) => ({
      ok: url === "http://127.0.0.1:7863/health",
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.resetModules();

    const { getBackendUrlAsync } = await import("../components/api");

    await expect(getBackendUrlAsync()).resolves.toBe("http://127.0.0.1:7863");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/health",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:7863/health",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("does not let the browser bridge prevent local backend health detection", async () => {
    const fetchMock = vi.fn(async (url: string) => ({
      ok: url === "http://127.0.0.1:7863/health",
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.resetModules();

    const { ensureBrowserBridge, getBackendUrlAsync } = await import("../components/api");

    ensureBrowserBridge();

    await expect(window.edmg?.getBackendUrl?.()).resolves.toBe("http://127.0.0.1:7863");
    await expect(getBackendUrlAsync()).resolves.toBe("http://127.0.0.1:7863");
  });
});
