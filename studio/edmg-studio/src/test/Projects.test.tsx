import React from "react";
import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Projects from "../pages/Projects";
import { installFetchMock, renderWithStudio } from "./testUtils";

describe("Projects page", () => {
  it("keeps project creation working while allowing layout changes", async () => {
    localStorage.removeItem("edmg_layout_projects_v1");

    const projects = [
      { id: "p1", name: "Starter Project", created_at: "2026-04-29T12:00:00Z" },
    ];

    installFetchMock({
      "GET /v1/projects": () => ({ projects: [...projects] }),
      "POST /v1/projects": (_path, init) => {
        const payload = JSON.parse(String(init?.body || "{}"));
        projects.push({
          id: `p${projects.length + 1}`,
          name: String(payload?.name || "Untitled"),
          created_at: "2026-04-29T12:05:00Z",
        });
        return { ok: true };
      },
    });

    renderWithStudio(<Projects backendUrl="http://127.0.0.1:7863" config={null} />);

    expect(await screen.findByRole("heading", { name: /Projects/i })).toBeTruthy();
    expect(screen.getByText(/Project layout/i)).toBeTruthy();
    expect(await screen.findByText(/Starter Project/i)).toBeTruthy();

    fireEvent.change(screen.getByDisplayValue("My Project"), {
      target: { value: "Launch Cut" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText(/Launch Cut/i)).toBeTruthy();

    const workflowLayoutItem = screen
      .getByText(/Next steps after creating a project\./i)
      .closest(".studio-layoutToolsItem");
    if (!(workflowLayoutItem instanceof HTMLElement)) {
      throw new Error("Workflow layout control not found");
    }

    fireEvent.click(within(workflowLayoutItem).getByRole("button", { name: "Hide" }));
    expect(
      screen.queryByText(/Use Workspace to select a project and run audio\/plan\/render\/export\./i),
    ).toBeNull();
  });
});
