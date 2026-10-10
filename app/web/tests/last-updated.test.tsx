import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Parcel } from "@parcel/core";
import { fakeService, renderApp } from "./helpers";

describe("parcel page — Last updated line", () => {
  it("shows the newest event timestamp as 'Last updated' below the status badge", async () => {
    // PK1000000001's newest event is 2026-10-10T06:42:00Z -> "10 Oct 2026, 06:42 UTC"
    renderApp(fakeService(), "#/parcel/PK1000000001");

    // wait for the timeline to render so the page is fully loaded
    await screen.findByRole("list", { name: "Shipment history" });

    // the parcel summary is the header with class parcel-header; find it by locating the page title
    const title = screen.getByRole("heading", { level: 1, name: "PK1000000001" });
    const header = title.closest(".parcel-header");
    expect(header).toBeInstanceOf(HTMLElement);

    // The exact line must be a real text node inside the parcel summary region and in reading order
    const parcelHeader = within(header as HTMLElement);
    expect(parcelHeader.getByText("Last updated: 10 Oct 2026, 06:42 UTC")).toBeInTheDocument();
  });

  it("does not render the 'Last updated' line when the parcel has no events", async () => {
    // Create a service that returns a parcel with no events
    const real = fakeService();
    const realGetParcel = real.getParcel as (tn: string) => Promise<Parcel>;

    async function getParcel(trackingNumber: string): Promise<Parcel> {
      const p = await realGetParcel(trackingNumber);
      return { ...p, events: [] } as Parcel;
    }

    renderApp(fakeService({ getParcel }), "#/parcel/PK1000000001");

    // wait for the page heading so the page is loaded
    await screen.findByRole("heading", { level: 1, name: "PK1000000001" });

    // The 'Last updated' text must not be present nor any spurious 'null'/'undefined'/'Invalid Date'
    expect(screen.queryByText(/Last updated:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/null|undefined|Invalid Date/)).not.toBeInTheDocument();
  });
});
