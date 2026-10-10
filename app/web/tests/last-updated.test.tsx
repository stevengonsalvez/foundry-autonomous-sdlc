import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Parcel } from "@parcel/core";
import { fakeService, renderApp } from "./helpers";

describe("parcel page — last updated line", () => {
  it("shows the Last updated line below the status badge with the newest event timestamp", async () => {
    renderApp(fakeService(), "#/parcel/PK1000000001");

    // Find the page heading and then the enclosing parcel header
    const heading = await screen.findByRole("heading", { level: 1, name: "PK1000000001" });
    const header = heading.closest("header");
    if (!header) throw new Error("parcel header not found");

    // The exact text and format required by the spec
    const expected = "Last updated: 10 Oct 2026, 06:42 UTC";
    // The line should be present inside the parcel header region
    expect(await within(header).findByText(expected)).toBeInTheDocument();
  });

  it("determines the newest event by timestamp regardless of the events array order", async () => {
    // Create a parcel where the events array is intentionally out of chronological order
    const parcel: Parcel = {
      trackingNumber: "PKTEST0000001",
      status: "in_transit",
      estimatedDelivery: null,
      // newest event (2026-10-10T07:55:00Z) is placed before an older one in the array
      events: [
        { timestamp: "2026-10-10T07:55:00Z", location: "Leeds, GB", description: "Out for delivery" },
        { timestamp: "2026-10-09T18:45:00Z", location: "Birmingham, GB", description: "Departed regional hub" },
      ],
    };

    const service = fakeService({ getParcel: vi.fn(async (tn: string) => (tn === "PKTEST0000001" ? parcel : Promise.reject(new Error("unexpected")))) });

    renderApp(service, "#/parcel/PKTEST0000001");

    const heading = await screen.findByRole("heading", { level: 1, name: "PKTEST0000001" });
    const header = heading.closest("header");
    if (!header) throw new Error("parcel header not found");

    // Expect the Last updated line to reflect the newest timestamp value (07:55 UTC)
    const expected = "Last updated: 10 Oct 2026, 07:55 UTC";
    expect(await within(header).findByText(expected)).toBeInTheDocument();
  });
});