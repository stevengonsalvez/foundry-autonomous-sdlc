import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { fakeService, renderApp } from "./helpers";

describe("theme toggle", () => {
  it('is present in the header with accessible name "Toggle theme" and has test id "theme-toggle"', async () => {
    renderApp(fakeService());
    // The toggle should be visible in the header on every page
    const toggle = await screen.findByRole("button", { name: "Toggle theme" });
    expect(toggle).toBeInTheDocument();
    expect(toggle).toHaveAttribute("data-testid", "theme-toggle");
  });

  it('clicking the toggle flips data-theme on the html element and writes the chosen value to localStorage', async () => {
    // Ensure a clean starting point
    localStorage.removeItem("theme");
    // Start render
    renderApp(fakeService());

    const toggle = await screen.findByRole("button", { name: "Toggle theme" });

    // Record initial theme on the html element
    const initial = document.documentElement.getAttribute("data-theme");

    // Click the toggle to switch theme
    await userEvent.click(toggle);

    const after = document.documentElement.getAttribute("data-theme");
    // Expect the attribute to have changed
    expect(after).not.toBe(initial);

    // Expect localStorage to contain either "light" or "dark"
    const stored = localStorage.getItem("theme");
    expect(stored === "light" || stored === "dark").toBe(true);

    // The stored value should match the html attribute
    expect(after).toBe(stored);
  });
});
