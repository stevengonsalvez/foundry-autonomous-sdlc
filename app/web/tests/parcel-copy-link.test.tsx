import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, afterEach } from "vitest";
import { fakeService, renderApp } from "./helpers";

// Tests for the new "Copy link" button next to the tracking number on the parcel page.
// These assert the presence of the button and aria-label, that clicking uses the
// navigator.clipboard API with the current URL, and that a temporary confirmation
// appears for two seconds.

describe("parcel page copy link", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders a Copy link button next to the tracking number with an accessible aria-label that includes the tracking number", async () => {
    renderApp(fakeService(), "#/parcel/PK1000000001");

    // Wait for the page to load (shipment history appears when loaded)
    await screen.findByRole("list", { name: "Shipment history" });

    // The tracking number heading must be present
    expect(screen.getByRole("heading", { level: 1, name: "PK1000000001" })).toBeInTheDocument();

    // The copy button should be present and have an aria-label that includes the tracking number
    const button = screen.getByRole("button", { name: /Copy link/i });
    expect(button).toBeInTheDocument();
    // aria-label should include the tracking number
    expect(button).toHaveAttribute("aria-label");
    expect(button.getAttribute("aria-label")).toContain("PK1000000001");
  });

  it("writes the current parcel URL to the clipboard and shows a temporary 2s confirmation", async () => {
    renderApp(fakeService(), "#/parcel/PK1000000001");

    await screen.findByRole("list", { name: "Shipment history" });

    // Mock clipboard
    const writeText = vi.fn().mockResolvedValue(undefined);
    // Assign a clipboard object on navigator for the test without using `any`
    (navigator as unknown as { clipboard?: { writeText: (s: string) => Promise<void> } }).clipboard = {
      writeText,
    };

    // Use fake timers so we can assert the confirmation disappears after 2s
    vi.useFakeTimers();

    const button = screen.getByRole("button", { name: /Copy link/i });
    await userEvent.click(button);

    // Expect clipboard.writeText called with the current full URL
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(window.location.href));

    // A visible confirmation should appear after successful copy
    const confirmation = await screen.findByText(/copied/i);
    expect(confirmation).toBeVisible();

    // Advance timers by 2 seconds (2000ms) and expect the confirmation to disappear
    vi.advanceTimersByTime(2000);

    await waitFor(() => expect(screen.queryByText(/copied/i)).not.toBeInTheDocument());
  });
});
