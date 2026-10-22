import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import type { Parcel } from "@parcel/core";
import { fakeService, renderApp } from "./helpers";

describe("last seen", () => {
  it("shows 'Last seen: Manchester Hub' directly below the 'Last updated' line", async () => {
    const base = await fakeService().getParcel("PK1000000001");
    const baseEvent = base.events[0];
    if (!baseEvent) throw new Error("Expected fixture to have events");

    const parcel: Parcel = {
      ...base,
      events: [
        {
          ...baseEvent,
          timestamp: "2026-10-08T10:00:00Z",
          location: "London Depot",
        },
        {
          ...baseEvent,
          timestamp: "2026-10-09T14:30:00Z",
          location: "Manchester Hub",
        },
      ],
    };

    renderApp(fakeService({ getParcel: () => Promise.resolve(parcel) }), "#/parcel/PK1000000001");

    const lastUpdated = await screen.findByText(/Last updated/i);
    const lastSeen = await screen.findByText("Last seen: Manchester Hub");

    expect(lastSeen).toBeVisible();
    expect(lastSeen.closest("[aria-hidden='true']")).toBeNull();
    expect(lastUpdated.compareDocumentPosition(lastSeen) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("uses the newest event by latest timestamp regardless of arrival order", async () => {
    const base = await fakeService().getParcel("PK1000000001");
    const baseEvent = base.events[0];
    if (!baseEvent) throw new Error("Expected fixture to have events");

    const parcel: Parcel = {
      ...base,
      events: [
        {
          ...baseEvent,
          timestamp: "2026-10-08T10:00:00Z",
          location: "London Depot",
        },
        {
          ...baseEvent,
          timestamp: "2026-10-10T16:30:00Z",
          location: "Manchester Hub",
        },
        {
          ...baseEvent,
          timestamp: "2026-10-09T12:00:00Z",
          location: "Birmingham Sorting Office",
        },
      ],
    };

    renderApp(fakeService({ getParcel: () => Promise.resolve(parcel) }), "#/parcel/PK1000000001");

    expect(await screen.findByText("Last seen: Manchester Hub")).toBeInTheDocument();
    expect(screen.queryByText(/Last seen: London Depot/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Last seen: Birmingham Sorting Office/)).not.toBeInTheDocument();
  });

  it("does not show the line and displays no null, undefined or empty 'Last seen:' when the parcel has no events", async () => {
    const base = await fakeService().getParcel("PK1000000001");

    const parcel: Parcel = {
      ...base,
      events: [],
    };

    renderApp(fakeService({ getParcel: () => Promise.resolve(parcel) }), "#/parcel/PK1000000001");

    await screen.findByRole("heading", { level: 1, name: "PK1000000001" });
    expect(screen.queryByText(/Last seen/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/null/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/undefined/i)).not.toBeInTheDocument();
  });

  it("does not show the line when the newest event has an empty location", async () => {
    const base = await fakeService().getParcel("PK1000000001");
    const baseEvent = base.events[0];
    if (!baseEvent) throw new Error("Expected fixture to have events");

    const parcel: Parcel = {
      ...base,
      events: [
        {
          ...baseEvent,
          timestamp: "2026-10-08T10:00:00Z",
          location: "London Depot",
        },
        {
          ...baseEvent,
          timestamp: "2026-10-10T16:30:00Z",
          location: "",
        },
      ],
    };

    renderApp(fakeService({ getParcel: () => Promise.resolve(parcel) }), "#/parcel/PK1000000001");

    await screen.findByRole("heading", { level: 1, name: "PK1000000001" });
    expect(screen.queryByText(/Last seen/i)).not.toBeInTheDocument();
  });
});
