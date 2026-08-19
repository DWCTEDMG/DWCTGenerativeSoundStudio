import React, { useState } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { StudioCommandPalette } from "../components/StudioCommandPalette";
import type { Page } from "../pageRouting";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

function installReadyStudio() {
  installEdmgBridge();
  installFetchMock({
    "/v1/config": {},
    "/v1/setup/status": {
      backend_bundle: { ok: true },
      ffmpeg: { ok: true },
      ollama: { ok: true, model_present: true },
      ai_config: { ollama_required: false, model_required: false },
    },
    "/health": { ok: true },
    "/v1/edmg/status": { ok: true },
    "/v1/projects": { projects: [] },
  });
}

function PaletteHarness() {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState<Page>("dashboard");
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open Studio search
      </button>
      <StudioCommandPalette
        open={open}
        activePage={page}
        onClose={() => setOpen(false)}
        onNavigate={setPage}
      />
    </>
  );
}

describe("Studio shell navigation", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/?page=dashboard&backendUrl=http%3A%2F%2F127.0.0.1%3A7863");
    document.title = "";
  });

  it("uses semantic landmarks, pushes page URLs, and follows popstate navigation", async () => {
    installReadyStudio();
    const pushState = vi.spyOn(window.history, "pushState");

    renderWithStudio(<App />);

    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeTruthy();
    const navigation = screen.getByRole("navigation", { name: "Studio screens and tools" });
    const main = screen.getByRole("main");
    const dashboardButton = within(navigation).getByRole("button", { name: /Dashboard/i });
    expect(dashboardButton.getAttribute("aria-current")).toBe("page");
    expect(document.title).toBe("Dashboard | EDMG Studio");

    fireEvent.click(within(navigation).getByRole("button", { name: /Projects/i }));

    expect(await screen.findByRole("heading", { name: "Projects" })).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(main));
    expect(document.title).toBe("Projects | EDMG Studio");
    expect(new URLSearchParams(window.location.search).get("page")).toBe("projects");
    expect(new URLSearchParams(window.location.search).get("backendUrl")).toBe(
      "http://127.0.0.1:7863",
    );
    expect(pushState).toHaveBeenCalledTimes(1);
    expect(String(pushState.mock.calls[0][2])).toContain("page=projects");
    expect(
      within(navigation).getByRole("button", { name: /Projects/i }).getAttribute("aria-current"),
    ).toBe("page");

    act(() => {
      window.history.replaceState({}, "", "/?page=dashboard&backendUrl=http%3A%2F%2F127.0.0.1%3A7863");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });

    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(main));
    expect(document.title).toBe("Dashboard | EDMG Studio");
  });

  it("opens and closes screen search with Ctrl/Cmd+K and lets the skip link focus main", async () => {
    installReadyStudio();
    renderWithStudio(<App />);
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeTruthy();

    const searchButton = screen.getByRole("button", { name: "Search Studio screens and tools" });
    searchButton.focus();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const dialog = await screen.findByRole("dialog", { name: "Search Studio screens and tools" });
    expect(dialog).toBeTruthy();
    await waitFor(() => {
      expect(document.activeElement).toBe(
        screen.getByRole("textbox", { name: "Search Studio screens and tools" }),
      );
    });

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(searchButton);

    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(await screen.findByRole("dialog", { name: "Search Studio screens and tools" })).toBeTruthy();
    fireEvent.keyDown(window, { key: "k", metaKey: true });

    const main = screen.getByRole("main");
    fireEvent.click(screen.getByRole("link", { name: "Skip to main content" }));
    await waitFor(() => expect(document.activeElement).toBe(main));
  });
});

describe("Studio command palette focus", () => {
  it("traps Tab inside the dialog and restores the opener on Escape", async () => {
    render(<PaletteHarness />);
    const opener = screen.getByRole("button", { name: "Open Studio search" });
    opener.focus();
    fireEvent.click(opener);

    const dialog = await screen.findByRole("dialog", { name: "Search Studio screens and tools" });
    const input = screen.getByRole("textbox", { name: "Search Studio screens and tools" });
    await waitFor(() => expect(document.activeElement).toBe(input));

    const dialogButtons = within(dialog).getAllByRole("button");
    const lastButton = dialogButtons[dialogButtons.length - 1];
    lastButton.focus();
    fireEvent.keyDown(lastButton, { key: "Tab" });
    expect(document.activeElement).toBe(input);

    input.focus();
    fireEvent.keyDown(input, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(lastButton);

    fireEvent.keyDown(input, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(opener);
  });
});
