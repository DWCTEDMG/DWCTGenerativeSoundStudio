import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useStudioPageLayout } from "../components/studioLayout";

function LayoutProbe() {
  const {
    activeProfile,
    visibleOrder,
    movePanel,
    updateHidden,
    resetLayout,
    setActiveProfile,
  } = useStudioPageLayout(
    "layout_probe",
    ["alpha", "beta", "gamma"] as const,
  );

  return (
    <div>
      <div data-testid="active-profile">{activeProfile}</div>
      <div data-testid="visible-order">{visibleOrder.join(",")}</div>
      <button onClick={() => movePanel("gamma", -1)}>Gamma Up</button>
      <button onClick={() => updateHidden("beta", true)}>Hide Beta</button>
      <button onClick={() => setActiveProfile("focus")}>Focus Profile</button>
      <button onClick={() => setActiveProfile("personal")}>Personal Profile</button>
      <button onClick={resetLayout}>Reset</button>
    </div>
  );
}

describe("useStudioPageLayout", () => {
  it("reorders, hides, and resets page panels", () => {
    render(<LayoutProbe />);

    expect(screen.getByTestId("visible-order").textContent).toBe("alpha,beta,gamma");

    fireEvent.click(screen.getByRole("button", { name: /Gamma Up/i }));
    expect(screen.getByTestId("visible-order").textContent).toBe("alpha,gamma,beta");

    fireEvent.click(screen.getByRole("button", { name: /Hide Beta/i }));
    expect(screen.getByTestId("visible-order").textContent).toBe("alpha,gamma");

    fireEvent.click(screen.getByRole("button", { name: /Reset/i }));
    expect(screen.getByTestId("visible-order").textContent).toBe("alpha,beta,gamma");
  });

  it("keeps layout profiles isolated per page", () => {
    render(<LayoutProbe />);

    fireEvent.click(screen.getByRole("button", { name: /Gamma Up/i }));
    fireEvent.click(screen.getByRole("button", { name: /Hide Beta/i }));

    expect(screen.getByTestId("active-profile").textContent).toBe("personal");
    expect(screen.getByTestId("visible-order").textContent).toBe("alpha,gamma");

    fireEvent.click(screen.getByRole("button", { name: /Focus Profile/i }));
    expect(screen.getByTestId("active-profile").textContent).toBe("focus");
    expect(screen.getByTestId("visible-order").textContent).toBe("alpha,beta,gamma");

    fireEvent.click(screen.getByRole("button", { name: /Gamma Up/i }));
    expect(screen.getByTestId("visible-order").textContent).toBe("alpha,gamma,beta");

    fireEvent.click(screen.getByRole("button", { name: /Personal Profile/i }));
    expect(screen.getByTestId("active-profile").textContent).toBe("personal");
    expect(screen.getByTestId("visible-order").textContent).toBe("alpha,gamma");
  });
});
