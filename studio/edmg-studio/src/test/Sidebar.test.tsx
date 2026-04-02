import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Sidebar from "../components/Sidebar";

describe("Sidebar", () => {
  it("uses a packaged-safe relative logo path", () => {
    render(<Sidebar page="dashboard" onNavigate={() => {}} />);

    const logo = screen.getByAltText("EDMG Studio logo");
    expect(logo.getAttribute("src")).toBe("studio-logo.png");
    expect(screen.getByRole("button", { name: "AI Planner Lab" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reactive Lab" })).toBeTruthy();
  });
});
