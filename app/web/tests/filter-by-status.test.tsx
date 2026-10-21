import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { ParcelSummary } from "@parcel/core";
import { fakeService, renderApp } from "./helpers";

// These tests assert the new client-side "Filter by status" control on the home page.
// They assume the control is visible, labelled "Filter by status", contains the exact
// visible options used by the status badges, performs filtering client-side using the
// already-loaded list, persists the selection in the URL as status=<value>, and
// respects a valid status query param on page load. They will fail on main where the
// control is not implemented yet.

describe("home page — filter by status control", () => {
  it("renders a labelled control with the required options and filters the loaded list client-side", async () => {
    renderApp(fakeService());

    // Control must be visible and labelled
    const select = await screen.findByLabelText("Filter by status");
    expect(select).toBeInTheDocument();

    // Options must include All parcels and the same human labels as the badges
    const withinSelect = within(select as Element);
    expect(withinSelect.getByRole("option", { name: "All parcels" })).toBeInTheDocument();
    expect(withinSelect.getByRole("option", { name: "Label created" })).toBeInTheDocument();
    expect(withinSelect.getByRole("option", { name: "In transit" })).toBeInTheDocument();
    expect(withinSelect.getByRole("option", { name: "Out for delivery" })).toBeInTheDocument();
    expect(withinSelect.getByRole("option", { name: "Delivered" })).toBeInTheDocument();
    expect(withinSelect.getByRole("option", { name: "Exception" })).toBeInTheDocument();

    // Initially the full recent parcels table is shown
    const table = await screen.findByRole("table", { name: "Recent parcels" });
    const allRows = within(table).getAllByRole("row").slice(1);
    expect(allRows.length).toBeGreaterThan(1);

    // Choose "Label created" and expect the list to filter client-side (no network)
    await userEvent.selectOptions(select, "label_created");

    // The URL must include the status query parameter so it can be shared
    expect(window.location.hash).toContain("status=label_created");

    // The table should now only show parcels with the Label created badge
    const rowsAfter = within(table).getAllByRole("row").slice(1);
    expect(rowsAfter.length).toBeGreaterThanOrEqual(1);
    // every visible row should contain the label text "Label created"
    for (const row of rowsAfter) {
      expect(within(row).getByText("Label created")).toBeVisible();
    }
  });

  it("applies a valid status from the URL on load and ignores unknown values", async () => {
    // Load the app with a valid status query param — should apply the filter on page load
    renderApp(fakeService(), "#/?status=out_for_delivery");

    const select = await screen.findByLabelText("Filter by status");
    // The select should reflect the valid status from the URL
    expect((select as HTMLSelectElement).value).toBe("out_for_delivery");

    const table = await screen.findByRole("table", { name: "Recent parcels" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.length).toBeGreaterThanOrEqual(1);
    // All visible rows should have the Out for delivery badge
    for (const row of rows) {
      expect(within(row).getByText("Out for delivery")).toBeVisible();
    }

    // Now render with an unknown/invalid status — it should be treated as All statuses
    renderApp(fakeService(), "#/?status=banana");
    const select2 = await screen.findByLabelText("Filter by status");
    expect((select2 as HTMLSelectElement).value).toBe("all");
    // Table should show full list again
    const table2 = await screen.findByRole("table", { name: "Recent parcels" });
    const rows2 = within(table2).getAllByRole("row").slice(1);
    expect(rows2.length).toBeGreaterThan(1);
  });

  it("is keyboard accessible (can receive focus) and shows a message when no parcels match", async () => {
    // Use a service that returns parcels that are not Delivered, then filter to Delivered
    const parcels = await fakeService().listParcels() as ParcelSummary[];
    // ensure none of the returned parcels are delivered for this test by mapping statuses
    const modified = parcels.map((p) => ({ ...p, status: "in_transit" as const }));
    const svc = fakeService({ listParcels: async () => modified });
    renderApp(svc);

    const select = await screen.findByLabelText("Filter by status");

    // Assert it can receive focus
    (select as HTMLElement).focus();
    expect(select).toHaveFocus();

    // Now choose "Delivered" which none of the parcels match
    await userEvent.selectOptions(select, "delivered");

    // Expect the empty-message for filtered results
    expect(await screen.findByText("No parcels match this status.")).toBeVisible();
    // And the table should not be present when there are no matches
    expect(screen.queryByRole("table", { name: "Recent parcels" })).not.toBeInTheDocument();
  });
});
