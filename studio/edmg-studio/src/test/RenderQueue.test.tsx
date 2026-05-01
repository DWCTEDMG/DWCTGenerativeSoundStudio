import React from "react";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import RenderQueue from "../pages/RenderQueue";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

describe("Render queue page", () => {
  it("ticks the worker through the backend queue endpoint", async () => {
    installEdmgBridge();
    const fetchMock = installFetchMock({
      "/v1/projects": { projects: [{ id: "p1", name: "Demo Project" }] },
      "/v1/jobs": { jobs: [] },
      "POST /v1/jobs/tick": { ok: true },
    });

    renderWithStudio(<RenderQueue backendUrl="http://127.0.0.1:7863" config={null} />);

    expect(await screen.findByRole("combobox", { name: "Render Queue layout profile" })).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: /Tick Worker/ }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url, init]) =>
          String(url).includes("/v1/jobs/tick") && String(init?.method || "GET").toUpperCase() === "POST"),
      ).toBe(true);
    });
  });
});
