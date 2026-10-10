import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { fakeService, renderApp } from "./helpers";

describe("home page — filter by status", () => {
  it("shows a labelled 'Filter by status' control", async () => {
    renderApp(fakeService());
    expect(await screen.findByLabelText("Filter by status")).toBeInTheDocument();
    // table still appears as the page loads
    await screen.findByRole("table");
  });

  it("selecting a status filters the visible parcel list and updates the URL", async () => {
    renderApp(fakeService());
    const table = await screen.findByRole("table", { name: "Recent parcels" });
    // initially there are 8 sample shipments
    const initialRows = within(table).getAllByRole("row").slice(1);
    expect(initialRows).toHaveLength(8);

    const select = await screen.findByLabelText("Filter by status");
    // choose the human label for delivered shipments
    await userEvent.selectOptions(select, "Delivered");

    // after filtering we expect only delivered parcels (two in the fixtures)
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByRole("link")).toHaveTextContent("PK1000000003");
    expect(within(rows[1]!).getByRole("link")).toHaveTextContent("PK1000000007");

    // the page URL should include the status query
    expect(window.location.hash).toMatch(/status=delivered/);
  });

  it("shows a helpful message when no parcels match the selected status and keeps the status in the URL", async () => {
    // make the list empty so any selection produces no results
    renderApp(fakeService({ listParcels: async () => [] }));
    await screen.findByRole("status"); // loading

    const select = await screen.findByLabelText("Filter by status");
    await userEvent.selectOptions(select, "Delivered");

    // With no parcels at all, the UI should tell the user there are no matches
    expect(await screen.findByText("No parcels match this status.")).toBeVisible();
    // and the selected status should remain reflected in the URL
    expect(window.location.hash).toMatch(/status=delivered/);
  });

  it("ignores an unknown status value in the URL and shows the full parcel list", async () => {
    // supply an unsupported status in the initial URL
    renderApp(fakeService(), "#/?status=bogus");
    const table = await screen.findByRole("table", { name: "Recent parcels" });
    const rows = within(table).getAllByRole("row").slice(1);
    // unknown status should result in no filtering: show all 8 sample shipments
    expect(rows).toHaveLength(8);
  });
});
