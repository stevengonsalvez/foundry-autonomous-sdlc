import { screen, within } from "@testing-library/react";
import { describe, it } from "vitest";
import { renderApp, fakeService } from "./helpers";

describe("estimated delivery", () => {
  it("shows the formatted estimated delivery beneath the status for applicable statuses", async () => {
    // PK1000000006 in fixtures: TRANSIT, eta: 2026-10-12
    renderApp(fakeService(), "#/parcel/PK1000000006");

    // Wait for timeline to appear to ensure page loaded
    await screen.findByRole("list", { name: "Shipment history" });

    // The exact expected text per spec (English UK, weekday short month year)
    expect(screen.getByText("Estimated delivery: Mon 12 Oct 2026")).toBeInTheDocument();

    // The line should be inside the parcel header / summary region (directly under status badge)
    const header = screen.getByRole("heading", { level: 1, name: "PK1000000006" }).closest(".parcel-header");
    expect(header).toBeTruthy();
    // Within the header we should find the estimated delivery text node
    expect(within(header as HTMLElement).getByText("Estimated delivery: Mon 12 Oct 2026")).toBeInTheDocument();
  });

  it("does not show the estimated delivery when the parcel is delivered", async () => {
    // PK1000000003 in fixtures: DELIVERED, eta: 2026-10-08
    renderApp(fakeService(), "#/parcel/PK1000000003");
    await screen.findByRole("list", { name: "Shipment history" });

    // When status is delivered, the estimated delivery line should not be present
    expect(screen.queryByText(/Estimated delivery:/)).not.toBeInTheDocument();
  });

  it("does not show the estimated delivery for exception or null eta and does not render null/Invalid Date", async () => {
    // PK1000000005 in fixtures: EXCEPTION, eta: null
    renderApp(fakeService(), "#/parcel/PK1000000005");
    await screen.findByRole("list", { name: "Shipment history" });

    // No estimated delivery line
    expect(screen.queryByText(/Estimated delivery:/)).not.toBeInTheDocument();

    // Also ensure UI doesn't render literal null/undefined/Invalid Date anywhere
    expect(screen.queryByText("null")).not.toBeInTheDocument();
    expect(screen.queryByText("undefined")).not.toBeInTheDocument();
    expect(screen.queryByText("Invalid Date")).not.toBeInTheDocument();
  });
});
