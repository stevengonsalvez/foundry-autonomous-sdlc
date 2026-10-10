import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { fakeService, renderApp } from "./helpers";

describe("estimated delivery", () => {
  it("shows the estimated delivery line below the status badge for in_transit parcels", async () => {
    // PK1000000006 in fixtures has state TRANSIT -> in_transit and eta "2026-10-12"
    renderApp(fakeService(), "#/parcel/PK1000000006");

    const header = await screen.findByRole("heading", { level: 1, name: "PK1000000006" });
    // parcel summary region is the element with class parcel-header
    const summary = document.querySelector(".parcel-header");
    expect(summary).toBeInstanceOf(HTMLElement);

    // The estimated delivery text must be a real text node inside the parcel summary region
    expect(within(summary as HTMLElement).getByText("Estimated delivery: Mon 12 Oct 2026")).toBeInTheDocument();

    // And the status badge still appears as before
    expect(within(summary as HTMLElement).getByText(/In transit/)).toBeVisible();
  });

  it("does not show estimated delivery when status is delivered or when eta is null/exception", async () => {
    // delivered parcel has an eta in fixtures but should not show the estimated delivery line
    renderApp(fakeService(), "#/parcel/PK1000000003");
    const summaryDelivered = document.querySelector(".parcel-header");
    await screen.findByRole("heading", { level: 1, name: "PK1000000003" });
    // The line must not be present for delivered
    expect(summaryDelivered).toBeInstanceOf(HTMLElement);
    expect(within(summaryDelivered as HTMLElement).queryByText(/Estimated delivery:/)).not.toBeInTheDocument();

    // exception with null eta must not show the line or any literal null/undefined/Invalid Date
    renderApp(fakeService(), "#/parcel/PK1000000005");
    const summaryException = document.querySelector(".parcel-header");
    await screen.findByRole("heading", { level: 1, name: "PK1000000005" });
    expect(summaryException).toBeInstanceOf(HTMLElement);
    const forbidden = within(summaryException as HTMLElement).queryByText(/null|undefined|Invalid Date/);
    expect(forbidden).not.toBeInTheDocument();
    expect(within(summaryException as HTMLElement).queryByText(/Estimated delivery:/)).not.toBeInTheDocument();
  });
});
