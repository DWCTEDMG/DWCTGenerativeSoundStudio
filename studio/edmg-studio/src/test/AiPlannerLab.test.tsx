import React from "react";
import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithStudio } from "./testUtils";

const setProjectId = vi.fn();
const refreshProject = vi.fn();
let lastPlannerProps: any = null;

vi.mock("../workbenches/useStudioWorkbenchProject", () => ({
  useStudioWorkbenchProject: () => ({
    projects: [{ id: "p1", name: "Planner Demo" }],
    projectId: "p1",
    setProjectId,
    selectedVariant: 2,
    setSelectedVariant: vi.fn(),
    project: { id: "p1", name: "Planner Demo" },
    refreshProjects: vi.fn(),
    refreshProject,
  }),
}));

vi.mock("../workbenches/AiNlpWorkbench", () => ({
  default: (props: any) => {
    lastPlannerProps = props;
    return React.createElement(
      "div",
      { className: "card", "data-testid": "planner-workbench" },
      `Planner workbench for ${props.studioProjectName}`,
    );
  },
}));

import AiPlannerLab from "../pages/AiPlannerLab";

describe("AI Planner Lab page", () => {
  beforeEach(() => {
    localStorage.clear();
    setProjectId.mockReset();
    refreshProject.mockReset();
    lastPlannerProps = null;
  });

  it("supports local layout customization without changing planner handoff props", async () => {
    const onNavigate = vi.fn();

    renderWithStudio(
      <AiPlannerLab backendUrl="http://127.0.0.1:7863" config={null} onNavigate={onNavigate} />,
    );

    expect(await screen.findByRole("heading", { name: "AI Planner Lab" })).toBeTruthy();
    expect(await screen.findByTestId("planner-workbench")).toBeTruthy();
    expect(lastPlannerProps?.studioProjectId).toBe("p1");
    expect(lastPlannerProps?.studioSelectedVariant).toBe(2);

    fireEvent.click(screen.getByRole("button", { name: "Workspace" }));
    expect(onNavigate).toHaveBeenCalledWith("workspace");

    const layoutDetails = screen.getByText("AI Planner Lab layout").closest("details");
    expect(layoutDetails).toBeTruthy();
    layoutDetails?.setAttribute("open", "");

    const profileSelect = screen.getByRole("combobox", { name: "AI Planner Lab layout profile" });
    expect(profileSelect).toBeTruthy();

    const bridgeControl = screen
      .getByText("Project targeting, renderer handoff context, and navigation back into the main Studio flow.")
      .closest(".studio-layoutToolsItem");
    expect(bridgeControl).toBeTruthy();

    fireEvent.click(within(bridgeControl as HTMLElement).getByRole("button", { name: "Hide" }));

    expect(screen.queryByText("Studio project")).toBeNull();
    expect(screen.getByTestId("planner-workbench")).toBeTruthy();
    expect(localStorage.getItem("edmg_layout_planner_lab_v1")).toContain("bridge");

    fireEvent.change(profileSelect, { target: { value: "focus" } });
    expect(localStorage.getItem("edmg_layout_planner_lab_active_profile_v1")).toBe("focus");
  });
});
