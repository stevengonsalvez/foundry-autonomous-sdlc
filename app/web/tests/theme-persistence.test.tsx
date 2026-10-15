import { describe, expect, it } from "vitest";
import { fakeService, renderApp } from "./helpers";

describe("theme persistence on load", () => {
  it('honours the stored value in localStorage on load and applies it to the html element', async () => {
    // Simulate a previously chosen dark theme
    localStorage.setItem("theme", "dark");

    // Render the app; the stored theme should be applied
    renderApp(fakeService());

    // The html element should have the stored data-theme before any interaction
    const applied = document.documentElement.getAttribute("data-theme");
    expect(applied).toBe("dark");

    // Clean up for other tests
    localStorage.removeItem("theme");
  });
});
