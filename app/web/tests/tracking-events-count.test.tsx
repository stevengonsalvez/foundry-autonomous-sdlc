import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Parcel, TrackingNumber } from "@parcel/core";
import { fakeService, renderApp } from "./helpers";

describe("parcel page — tracking events count", () => {
  it("shows 'Tracking events: X' below the Last updated line when there are multiple events", async () => {
    const parcel: Parcel = {
      trackingNumber: "PK1000000091" as TrackingNumber,
      status: "in_transit",
      estimatedDelivery: null,
      events: [
        { timestamp: "2026-10-08T16:30:00Z", location: "Rotterdam, NL", description: "Shipping label created" },
        { timestamp: "2026-10-09T10:00:00Z", location: "Rotterdam, NL", description: "Arrived at sorting hub" },
        { timestamp: "2026-10-10T08:15:00Z", location: "Amsterdam, NL", description: "Departed sorting hub" },
        { timestamp: "2026-10-11T12:00:00Z", location: "Utrecht, NL", description: "In transit" },
      ],
    };

    const getParcel = vi.fn().mockResolvedValue(parcel);
    renderApp(fakeService({ getParcel }), "#/parcel/PK1000000091");

    // Wait for the timeline to load to ensure the header is in final state
    await screen.findByRole("list", { name: "Shipment history" });

    const heading = screen.getByRole("heading", { level: 1, name: "PK1000000091" });
    const header = heading.closest(".parcel-header");
    expect(header).toBeInstanceOf(HTMLElement);
    const hdr = header as HTMLElement;

    // Get the paragraph elements inside the header; narrow types to HTMLParagraphElement
    const lastUpdated = within(hdr).getByText(/^Last updated:/) as HTMLParagraphElement;
    const count = within(hdr).getByText("Tracking events: 4") as HTMLParagraphElement;

    // The tracking events line is a real text node inside the parcel header and visible
    expect(count).toBeVisible();

    // It appears after the Last updated line in DOM order
    const paras = Array.from(hdr.querySelectorAll("p")) as HTMLParagraphElement[];
    expect(paras.indexOf(lastUpdated)).toBeGreaterThan(-1);
    expect(paras.indexOf(count)).toBeGreaterThan(paras.indexOf(lastUpdated));
  });

  it("shows 'Tracking events: 1' when there is exactly one event", async () => {
    const parcel: Parcel = {
      trackingNumber: "PK1000000092" as TrackingNumber,
      status: "in_transit",
      estimatedDelivery: null,
      events: [{ timestamp: "2026-10-11T12:00:00Z", location: "Utrecht, NL", description: "In transit" }],
    };

    const getParcel = vi.fn().mockResolvedValue(parcel);
    renderApp(fakeService({ getParcel }), "#/parcel/PK1000000092");

    await screen.findByRole("list", { name: "Shipment history" });

    const heading = screen.getByRole("heading", { level: 1, name: "PK1000000092" });
    const header = heading.closest(".parcel-header") as HTMLElement;

    expect(within(header).getByText("Tracking events: 1")).toBeVisible();
  });

  it("does not show the tracking events line when there are no events and does not render 'null'/'undefined'/'NaN'", async () => {
    const parcel: Parcel = {
      trackingNumber: "PK1000000093" as TrackingNumber,
      status: "in_transit",
      estimatedDelivery: null,
      events: [],
    };

    const getParcel = vi.fn().mockResolvedValue(parcel);
    renderApp(fakeService({ getParcel }), "#/parcel/PK1000000093");

    await screen.findByRole("list", { name: "Shipment history" });

    const heading = screen.getByRole("heading", { level: 1, name: "PK1000000093" });
    const header = heading.closest(".parcel-header") as HTMLElement;

    // The header should not contain any tracking events text
    expect(within(header).queryByText(/^Tracking events:/)).toBeNull();

    // And it must not accidentally display null/undefined/NaN anywhere in the header
    const html = header.textContent ?? "";
    expect(html).not.toContain("null");
    expect(html).not.toContain("undefined");
    expect(html).not.toContain("NaN");
  });
});
