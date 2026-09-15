import React from "react";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { installFetchMock, renderWithStudio } from "./testUtils";

const setProjectId = vi.fn();
const refreshProject = vi.fn();
let lastReactiveProps: any = null;

vi.mock("../workbenches/useStudioWorkbenchProject", () => ({
  useStudioWorkbenchProject: () => ({
    projects: [{ id: "p9", name: "Reactive Demo" }],
    projectId: "p9",
    setProjectId,
    selectedVariant: 1,
    setSelectedVariant: vi.fn(),
    project: { id: "p9", name: "Reactive Demo" },
    refreshProjects: vi.fn(),
    refreshProject,
  }),
}));

vi.mock("../workbenches/AudioReactiveWorkbench", () => ({
  default: (props: any) => {
    lastReactiveProps = props;
    return React.createElement(
      "div",
      { className: "card", "data-testid": "reactive-workbench" },
      `Reactive workbench for ${props.studioProjectName}`,
    );
  },
}));

import ReactiveLab from "../pages/ReactiveLab";

describe("Reactive Lab page", () => {
  beforeEach(() => {
    localStorage.clear();
    setProjectId.mockReset();
    refreshProject.mockReset();
    lastReactiveProps = null;
    installFetchMock({
      "GET /v1/projects/p9/director/workflow": {
        revision: 7,
        status: "draft",
        draft: { draft_id: "draft-a" },
        reactive: { metadata: { workflow_draft_id: "draft-a" }, keyframes: [] },
      },
    });
  });

  it("supports local layout customization while keeping reactive navigation intact", async () => {
    const onNavigate = vi.fn();

    renderWithStudio(
      <ReactiveLab backendUrl="http://127.0.0.1:7863" config={null} onNavigate={onNavigate} />,
    );

    expect(await screen.findByRole("heading", { name: "Reactive Lab" })).toBeTruthy();
    expect(await screen.findByTestId("reactive-workbench")).toBeTruthy();
    expect(lastReactiveProps?.studioProjectId).toBe("p9");
    expect(lastReactiveProps?.studioSelectedVariant).toBe(1);

    fireEvent.click(screen.getByRole("button", { name: "Outputs" }));
    expect(onNavigate).toHaveBeenCalledWith("outputs");

    const layoutDetails = screen.getByText("Reactive Lab layout").closest("details");
    expect(layoutDetails).toBeTruthy();
    layoutDetails?.setAttribute("open", "");

    const profileSelect = screen.getByRole("combobox", { name: "Reactive Lab layout profile" });
    expect(profileSelect).toBeTruthy();

    const bridgeControl = screen
      .getByText("Project targeting, renderer handoff context, and navigation back into the main Studio flow.")
      .closest(".studio-layoutToolsItem");
    expect(bridgeControl).toBeTruthy();

    fireEvent.click(within(bridgeControl as HTMLElement).getByRole("button", { name: "Hide" }));

    expect(screen.queryByText("Studio project")).toBeNull();
    expect(screen.getByTestId("reactive-workbench")).toBeTruthy();
    expect(localStorage.getItem("edmg_layout_reactive_lab_v1")).toContain("bridge");

    fireEvent.change(profileSelect, { target: { value: "presentation" } });
    expect(localStorage.getItem("edmg_layout_reactive_lab_active_profile_v1")).toBe("presentation");
  });

  it("reviews then explicitly applies the canonical revision-aware workflow", async () => {
    const requests: Array<{ path: string; body: any }> = [];
    const fetchMock = installFetchMock({
      "GET /v1/projects/p9/director/workflow": {
        revision: 7, status: "draft", draft: { draft_id: "draft-a" }, reactive: { keyframes: [] },
      },
      "POST /v1/projects/p9/director/workflow/reactive/review": (_path, init) => {
        requests.push({ path: "review", body: JSON.parse(String(init?.body)) });
        return { revision: 8, status: "draft", draft: { draft_id: "draft-b" } };
      },
      "POST /v1/projects/p9/director/workflow/apply": (_path, init) => {
        requests.push({ path: "apply", body: JSON.parse(String(init?.body)) });
        return { revision: 9, status: "applied", draft: { draft_id: "draft-b" } };
      },
    });
    renderWithStudio(<ReactiveLab backendUrl="http://127.0.0.1:7863" config={null} />);
    await waitFor(() => expect(lastReactiveProps?.studioWorkflowDraftId).toBe("draft-a"));
    await lastReactiveProps.onSyncToStudio({ metadata: {}, keyframes: [] });
    expect(requests).toEqual([
      { path: "review", body: { draft_id: "draft-a", expected_revision: 7, payload: { metadata: {}, keyframes: [] } } },
      { path: "apply", body: { draft_id: "draft-b", expected_revision: 8 } },
    ]);
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("reactive_lab/apply"))).toBe(false);
  });

  it("blocks stale drafts without touching the Timeline", async () => {
    const fetchMock = installFetchMock({
      "GET /v1/projects/p9/director/workflow": {
        revision: 9, status: "stale", draft: { draft_id: "old-draft" }, reactive: { keyframes: [] },
      },
    });
    renderWithStudio(<ReactiveLab backendUrl="http://127.0.0.1:7863" config={null} />);
    await screen.findByText(/prepared Workspace draft is stale/i);
    await expect(lastReactiveProps.onSyncToStudio({ keyframes: [] })).rejects.toThrow(/stale/i);
    expect(fetchMock.mock.calls.every(([, init]) => !init || String(init.method || "GET") === "GET")).toBe(true);
  });
});
