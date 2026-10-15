import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { fakeService, renderApp } from "./helpers";

// Mobile behaviour test: toggle open, Escape closes and focus returns
describe("side navigation (mobile)", () => {
  it("shows a top bar menu button that opens the navigation panel, and Escape closes it returning focus to the button", async () => {
    // Simulate a narrow viewport
    (window as unknown as { innerWidth: number }).innerWidth = 390;
    window.dispatchEvent(new Event("resize"));

    renderApp(fakeService(), "#/");

    const toggle = await screen.findByTestId("nav-toggle");
    expect(toggle).toBeInTheDocument();
    expect(toggle).toHaveAccessibleName("Open navigation");

    // Open the panel
    await userEvent.click(toggle);

    // The panel should contain the same links
    const panel = await screen.findByRole("dialog");
    expect(within(panel).getByRole("link", { name: "Track a parcel" })).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Recent parcels" })).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Status guide" })).toBeInTheDocument();

    // Press Escape to close
    await userEvent.keyboard("{Escape}");

    // The panel should no longer be in the document and focus should return to the toggle
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(toggle).toHaveFocus();
  });
});
