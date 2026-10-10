import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ParcelSummary } from "@parcel/core";
import { fakeService, renderApp } from "./helpers";

describe("Filter by status control", () => {
  it("is present with the exact labelled options and is keyboard-focusable", async () => {
    renderApp(fakeService());

    // The control should be labelled exactly "Filter by status" and be focusable
    const control = await screen.findByLabelText("Filter by status");
    expect(control).toBeInTheDocument();

    // Tab to the control to ensure it's focusable via keyboard
    await userEvent.tab();
    // If the first tabbable element isn't our control, keep tabbing until we find it
    // (tests shouldn't rely on a specific tab order outside the app)
    while (document.activeElement !== control) {
      await userEvent.tab();
    }
    expect(document.activeElement).toBe(control);

    // Options must be shown in the exact order and text
    const options = Array.from((control as HTMLSelectElement).options).map((o) => o.textContent);
    expect(options).toEqual([
      "All statuses",
      "Label created",
      "In transit",
      "Out for delivery",
      "Delivered",
      "Exception",
    ]);
  });

  it("filters the already-loaded parcel list client-side and updates the URL without extra API calls", async () => {
    const svc = fakeService();
    renderApp(svc);

    // Wait for the full table to appear
    const table = await screen.findByRole("table", { name: "Recent parcels" });
    const rowsBefore = within(table).getAllByRole("row").slice(1);
    expect(rowsBefore).toHaveLength(8); // fixtures contain 8 sample shipments

    // Select "In transit" and ensure the list is filtered client-side
    const control = screen.getByLabelText("Filter by status");
    await userEvent.selectOptions(control, "in_transit");

    // The URL query should be updated to include status=in_transit
    expect(window.location.hash).toContain("status=in_transit");

    const rowsAfter = within(table).getAllByRole("row").slice(1);
    // Fixtures have 2 parcels with in_transit
    expect(rowsAfter).toHaveLength(2);

    // Ensure we didn't call the API again when filtering (client-side only)
    expect((svc.listParcels as unknown as jest.Mock) ? (svc.listParcels as unknown as jest.Mock).mock.calls.length : (svc.listParcels as any).mock?.calls.length).toBeDefined();
    // The listParcels spy should have been called exactly once during initial load
    expect((svc.listParcels as unknown as { mock?: { calls: unknown[] } }).mock?.calls.length ?? (svc.listParcels as any).mock.calls.length).toBe(1);
  });

  it("ignores an unknown status in the URL and shows all parcels", async () => {
    // Put an invalid status in the hash before rendering
    const hash = "#/?status=not_a_status";
    renderApp(fakeService(), hash);

    const table = await screen.findByRole("table", { name: "Recent parcels" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(8); // show all parcels when status is invalid
  });

  it("shows a specific message when no parcel matches the selected status", async () => {
    // Provide a service that returns a single delivered parcel so another status yields no matches
    const onlyDelivered: ParcelSummary = {
      trackingNumber: "PK9999999999" as any,
      status: "delivered",
      estimatedDelivery: null,
      lastUpdate: "2026-10-01T00:00:00Z",
    };
    const svc = fakeService({ listParcels: async () => [onlyDelivered] });
    renderApp(svc);

    // Ensure the table is present with one row initially
    const table = await screen.findByRole("table", { name: "Recent parcels" });
    expect(within(table).getAllByRole("row").slice(1)).toHaveLength(1);

    // Select a status that doesn't match the single delivered parcel
    const control = screen.getByLabelText("Filter by status");
    await userEvent.selectOptions(control, "in_transit");

    // The table should be replaced by the exact message
    expect(await screen.findByText("No parcels match this status.")).toBeInTheDocument();
  });

  it("persists the selected status from the URL on reload", async () => {
    // Pre-set the hash to request in_transit
    const hash = "#/?status=in_transit";
    renderApp(fakeService(), hash);

    // Table should be filtered to the two in_transit parcels
    const table = await screen.findByRole("table", { name: "Recent parcels" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);

    // The select control should reflect the selected status
    const control = screen.getByLabelText("Filter by status") as HTMLSelectElement;
    expect(control.value).toBe("in_transit");
  });
});
