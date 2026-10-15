import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { fakeService, renderApp } from "./helpers";

describe("home page theme end-to-end", () => {
  it('renders the home page with data-theme="dark" when localStorage has theme=dark', async () => {
    // Prepare persisted preference
    localStorage.setItem("theme", "dark");

    // Navigate to home and render
    renderApp(fakeService(), "#/" );

    // Wait for a stable element on the home page (the recent parcels table or the heading)
    await screen.findByRole("heading", { level: 1, name: "Track a parcel" });

    // The document element must have the data-theme attribute set to dark
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");

    // Clean up
    localStorage.removeItem("theme");
  });
});
