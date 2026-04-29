import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  STUDIO_THEME_OPTIONS,
  StudioAppearanceProvider,
  useStudioAppearance,
} from "../components/studioAppearance";

function ThemeProbe() {
  const { theme, setTheme } = useStudioAppearance();
  return (
    <div>
      <div data-testid="theme-value">{theme}</div>
      {STUDIO_THEME_OPTIONS.map((option) => (
        <button key={option.id} onClick={() => setTheme(option.id)}>
          {option.label}
        </button>
      ))}
    </div>
  );
}

describe("StudioAppearanceProvider", () => {
  it("defaults to the studio theme and applies the dataset", () => {
    render(
      <StudioAppearanceProvider>
        <ThemeProbe />
      </StudioAppearanceProvider>,
    );

    expect(screen.getByTestId("theme-value").textContent).toBe("studio");
    expect(document.documentElement.dataset.studioTheme).toBe("studio");
  });

  it("persists and applies theme changes", () => {
    render(
      <StudioAppearanceProvider>
        <ThemeProbe />
      </StudioAppearanceProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: /Ember/i }));

    expect(screen.getByTestId("theme-value").textContent).toBe("ember");
    expect(localStorage.getItem("edmg_studio_theme_v1")).toBe("ember");
    expect(document.documentElement.dataset.studioTheme).toBe("ember");
  });
});
