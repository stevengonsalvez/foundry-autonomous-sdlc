import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { deferred, fakeService, renderApp } from "./helpers";

describe("estimated delivery", () => {
  it("shows the estimated delivery below the status badge when present and status is in_transit", async () => {
    const parcel = {
      trackingNumber: "PK123",
      status: "in_transit",
      estimatedDelivery: "2026-10-12",
      events: [],
    };
    const getParcel = vi.fn(() => Promise.resolve(parcel));
    renderApp(fakeService({ getParcel }), "#/parcel/PK123");

    // Heading is immediate; the estimated delivery line appears after loading
    const heading = await screen.findByRole("heading", { level: 1, name: "PK123" });
    // The status badge and the date line should be in the parcel header region
    const header = heading.closest(".parcel-header");
    expect(header).toBeInTheDocument();

    // The page must show the status badge first
    expect(within(header as Element).getByText("In transit")).toBeVisible();

    // The acceptance criteria requires the exact formatted text (weekday short-month year, en-GB)
    // Example: 'Estimated delivery: Mon 12 Oct 2026'
    expect(await within(header as Element).findByText("Estimated delivery: Mon 12 Oct 2026")).toBeInTheDocument();
  });

  it("does not show the estimated delivery when the status is delivered", async () => {
    const parcel = {
      trackingNumber: "PKDEL",
      status: "delivered",
      estimatedDelivery: "2026-10-12",
      events: [],
    };
    const getParcel = vi.fn(() => Promise.resolve(parcel));
    renderApp(fakeService({ getParcel }), "#/parcel/PKDEL");

    await screen.findByRole("heading", { level: 1, name: "PKDEL" });
    // The line must not be present for delivered parcels
    expect(screen.queryByText(/Estimated delivery:/)).not.toBeInTheDocument();
  });

  it("does not render a line or any literal 'null', 'undefined' or 'Invalid Date' when status is exception or estimatedDelivery is null", async () => {
    const parcel = {
      trackingNumber: "PKEXC",
      status: "exception",
      estimatedDelivery: null,
      events: [],
    };
    const getParcel = vi.fn(() => Promise.resolve(parcel));
    renderApp(fakeService({ getParcel }), "#/parcel/PKEXC");

    await screen.findByRole("heading", { level: 1, name: "PKEXC" });
    expect(screen.queryByText(/Estimated delivery:/)).not.toBeInTheDocument();
    expect(screen.queryByText("null")).not.toBeInTheDocument();
    expect(screen.queryByText("undefined")).not.toBeInTheDocument();
    expect(screen.queryByText("Invalid Date")).not.toBeInTheDocument();
  });
});