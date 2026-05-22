import React from "react";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Cloud from "../pages/Cloud";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

describe("Cloud page", () => {
  it("keeps AWS test actions working while exposing layout profiles", async () => {
    installEdmgBridge();
    const fetchMock = installFetchMock({
      "POST /v1/cloud/aws/test": { ok: true, provider: "aws", bucket: "demo-bucket" },
    });

    renderWithStudio(<Cloud backendUrl="http://127.0.0.1:7863" config={null} />);

    expect(await screen.findByRole("combobox", { name: "Cloud layout profile" })).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText("my-bucket"), {
      target: { value: "demo-bucket" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Test credentials" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url, init]) =>
          String(url).includes("/v1/cloud/aws/test")
          && String(init?.method || "GET").toUpperCase() === "POST"
          && String(init?.body || "").includes("demo-bucket")),
      ).toBe(true);
    });
  });

  it("posts Azure model cache credential tests with the selected container", async () => {
    installEdmgBridge();
    const fetchMock = installFetchMock({
      "POST /v1/cloud/azure/test": { ok: true, provider: "azure", container: "edmg-model-cache" },
    });

    renderWithStudio(<Cloud backendUrl="http://127.0.0.1:7863" config={null} />);

    fireEvent.change(await screen.findByPlaceholderText("edmg-model-cache"), {
      target: { value: "team-model-cache" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Test Azure" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url, init]) =>
          String(url).includes("/v1/cloud/azure/test")
          && String(init?.method || "GET").toUpperCase() === "POST"
          && String(init?.body || "").includes("team-model-cache")),
      ).toBe(true);
    });
  });
});
