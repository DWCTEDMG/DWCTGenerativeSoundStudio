import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Sidebar from "../components/Sidebar";

describe("Sidebar", () => {
  it("uses grouped navigation while keeping standalone labs available", () => {
    render(<Sidebar page="plannerLab" onNavigate={() => {}} />);

    const logo = screen.getByAltText("EDMG Studio logo");
    expect(logo.getAttribute("src")).toBe("studio-logo.png");
    expect(screen.getByText("Labs")).toBeTruthy();
    expect(screen.getByRole("button", { name: /AI Planner Lab/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Reactive Lab/i })).toBeTruthy();
  });
});
