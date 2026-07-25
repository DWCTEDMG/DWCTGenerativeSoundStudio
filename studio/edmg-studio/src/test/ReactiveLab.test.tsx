import React from "react";
import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithStudio } from "./testUtils";

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
});
