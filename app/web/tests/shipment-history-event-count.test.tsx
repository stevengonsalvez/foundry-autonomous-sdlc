import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import type { TrackingNumber } from "@parcel/core";
import { fakeService, renderApp } from "./helpers";

describe("shipment history event count", () => {
  it("displays the event count in parentheses next to the shipment history heading when events exist", async () => {
    const service = fakeService();
    const base = await service.getParcel("PK1000000001" as TrackingNumber);
    const parcel = { ...base, events: base.events.slice(0, 3) };
    renderApp(fakeService({ getParcel: async () => parcel }), "#/parcel/PK1000000001");

    const heading = await screen.findByRole("heading", { name: "Shipment history (3)" });
    expect(heading).toBeInTheDocument();
  });

  it("displays 'Shipment history (1)' when there is exactly one event", async () => {
    const service = fakeService();
    const base = await service.getParcel("PK1000000001" as TrackingNumber);
    const parcel = { ...base, events: base.events.slice(0, 1) };
    renderApp(fakeService({ getParcel: async () => parcel }), "#/parcel/PK1000000001");

    const heading = await screen.findByRole("heading", { name: "Shipment history (1)" });
    expect(heading).toBeInTheDocument();
  });

  it("displays 'Shipment history' without a count when there are no events", async () => {
    const service = fakeService();
    const base = await service.getParcel("PK1000000001" as TrackingNumber);
    const parcel = { ...base, events: [] };
    renderApp(fakeService({ getParcel: async () => parcel }), "#/parcel/PK1000000001");

    const heading = await screen.findByRole("heading", { name: "Shipment history" });
    expect(heading).toBeInTheDocument();
    expect(heading).toHaveTextContent(/^Shipment history$/);
  });

  it("includes the count in the heading text node while preserving its id and link to the timeline", async () => {
    const service = fakeService();
    const base = await service.getParcel("PK1000000001" as TrackingNumber);
    const parcel = { ...base, events: base.events.slice(0, 3) };
    renderApp(fakeService({ getParcel: async () => parcel }), "#/parcel/PK1000000001");

    const heading = await screen.findByRole("heading", { name: "Shipment history (3)" });
    expect(heading).toHaveAttribute("id");
    expect(heading.textContent).toBe("Shipment history (3)");
    const timeline = await screen.findByRole("list", { name: /Shipment history/ });
    expect(timeline).toBeInTheDocument();
  });
});
