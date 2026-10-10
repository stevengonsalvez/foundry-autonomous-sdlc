import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { type Parcel } from "@parcel/core";
import { fakeService, renderApp } from "./helpers";

/*
Tests for: Show the estimated delivery date on the parcel page beneath the status badge

These tests assert the presence or absence of the exact text line
"Estimated delivery: Mon 12 Oct 2026" depending on parcel status and estimatedDelivery value.
They also assert the date text is a real text node inside the parcel summary/header region.
*/

describe("estimated delivery line on parcel page", () => {
  it("shows the formatted estimated delivery beneath the status badge for in_transit", async () => {
    const parcel: Parcel = {
      trackingNumber: "PKTEST0000001",
      status: "in_transit",
      estimatedDelivery: "2026-10-12",
      // minimal events to render the timeline
      events: [
        { description: "Shipping label created", location: "Rotterdam, NL", timestamp: "2026-10-08T16:30:00Z" },
      ],
    } as unknown as Parcel;

    renderApp(fakeService({ getParcel: () => Promise.resolve(parcel) }), "#/parcel/PKTEST0000001");

    // The header with the tracking number should be present
    expect(await screen.findByRole("heading", { level: 1, name: "PKTEST0000001" })).toBeInTheDocument();

    // The exact formatted line should be shown (weekday, day, short month, year, English UK)
    const expected = "Estimated delivery: Mon 12 Oct 2026";
    const header = within(document.querySelector(".parcel-header") as Element);
    // The line must be a real text node inside the parcel header (reading order)
    expect(header.getByText(expected)).toBeInTheDocument();
  });

  it("does not show the estimated delivery line when status is delivered", async () => {
    const parcel: Parcel = {
      trackingNumber: "PKTEST0000002",
      status: "delivered",
      estimatedDelivery: "2026-10-12",
      events: [
        { description: "Delivered, signed for by recipient", location: "Somewhere", timestamp: "2026-10-12T10:00:00Z" },
      ],
    } as unknown as Parcel;

    renderApp(fakeService({ getParcel: () => Promise.resolve(parcel) }), "#/parcel/PKTEST0000002");

    await screen.findByRole("heading", { level: 1, name: "PKTEST0000002" });

    // The exact estimated delivery text must NOT be present for delivered parcels
    const notExpected = "Estimated delivery: Mon 12 Oct 2026";
    expect(screen.queryByText(notExpected)).not.toBeInTheDocument();
  });

  it("does not show the estimated delivery line when status is exception or estimatedDelivery is null", async () => {
    const exceptionParcel: Parcel = {
      trackingNumber: "PKTEST0000003",
      status: "exception",
      estimatedDelivery: "2026-10-12",
      events: [
        { description: "Problem with delivery", location: "Hub", timestamp: "2026-10-10T09:00:00Z" },
      ],
    } as unknown as Parcel;

    const nullParcel: Parcel = {
      trackingNumber: "PKTEST0000004",
      status: "in_transit",
      estimatedDelivery: null,
      events: [
        { description: "Departed sorting hub", location: "Hub", timestamp: "2026-10-11T09:00:00Z" },
      ],
    } as unknown as Parcel;

    // Exception status with a non-null estimatedDelivery should NOT show the line
    renderApp(fakeService({ getParcel: () => Promise.resolve(exceptionParcel) }), "#/parcel/PKTEST0000003");
    await screen.findByRole("heading", { level: 1, name: "PKTEST0000003" });
    expect(screen.queryByText("Estimated delivery: Mon 12 Oct 2026")).not.toBeInTheDocument();

    // Null estimatedDelivery should not render the line or display 'null'/'undefined'/'Invalid Date'
    renderApp(fakeService({ getParcel: () => Promise.resolve(nullParcel) }), "#/parcel/PKTEST0000004");
    await screen.findByRole("heading", { level: 1, name: "PKTEST0000004" });
    expect(screen.queryByText("Estimated delivery: Mon 12 Oct 2026")).not.toBeInTheDocument();
    expect(screen.queryByText(/null|undefined|Invalid Date/)).not.toBeInTheDocument();
  });
});
