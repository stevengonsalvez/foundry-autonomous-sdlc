import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { fakeService, renderApp } from "./helpers";

// End-to-end style checks for responsive visibility
describe("side navigation responsive visibility", () => {
  it("shows left-nav at 1440px and hides it at 390px where nav-toggle is visible", async () => {
    // Wide viewport
    (window as unknown as { innerWidth: number }).innerWidth = 1440;
    window.dispatchEvent(new Event("resize"));

    renderApp(fakeService(), "#/");

    const leftNav = await screen.findByTestId("left-nav");
    expect(leftNav).toBeVisible();

    // Now narrow viewport
    (window as unknown as { innerWidth: number }).innerWidth = 390;
    window.dispatchEvent(new Event("resize"));

    // The left-nav should be hidden and the toggle should be visible
    const toggle = await screen.findByTestId("nav-toggle");
    expect(toggle).toBeVisible();

    // left-nav should no longer be visible if the app hides it on small screens
    const maybeLeft = screen.queryByTestId("left-nav");
    // If the element remains in the DOM but is hidden via CSS, not.toBeVisible will catch that
    expect(maybeLeft).not.toBeVisible();
  });
});
