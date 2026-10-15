import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { fakeService, renderApp } from "./helpers";

// Component test: checks presence of sidebar nav and aria-current on home and parcel pages
describe("side navigation (desktop)", () => {
  it("renders the left navigation with the Parcel Tracker logo and links, and marks the current page with aria-current=\"page\"", async () => {
    renderApp(fakeService(), "#/");

    // The left navigation should be present on wide viewports (implementation should show it by default in tests)
    const leftNav = await screen.findByTestId("left-nav");
    expect(leftNav).toBeInTheDocument();

    // It should be a nav landmark with accessible name "Main navigation"
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(nav).toBeInTheDocument();

    // Logo text (Parcel Tracker) should be inside the nav
    expect(within(nav).getByText("Parcel Tracker")).toBeInTheDocument();

    // Links exist
    expect(within(nav).getByRole("link", { name: "Track a parcel" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Recent parcels" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Status guide" })).toBeInTheDocument();

    // On the home page "Track a parcel" should be marked as the current page
    const homeLink = within(nav).getByRole("link", { name: "Track a parcel" });
    expect(homeLink).toHaveAttribute("aria-current", "page");

    // Navigate to a parcel page and ensure the nav still shows and home link points back to home
    renderApp(fakeService(), "#/parcel/PK1000000001");
    const navOnParcel = await screen.findByRole("navigation", { name: "Main navigation" });
    const trackLink = within(navOnParcel).getByRole("link", { name: "Track a parcel" });
    expect(trackLink).toHaveAttribute("href", "#/" );
  });
});
