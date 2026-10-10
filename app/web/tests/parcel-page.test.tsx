import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  CarrierUnavailableError,
  InvalidTrackingNumberError,
  ParcelNotFoundError,
  type Parcel,
} from "@parcel/core";
import { deferred, fakeService, renderApp } from "./helpers";

describe("parcel page", () => {
  it("shows the tracking number, the status badge and the timeline oldest first", async () => {
    renderApp(fakeService(), "#/parcel/PK1000000001");

    expect(screen.getByRole("heading", { level: 1, name: "PK1000000001" })).toBeInTheDocument();
    const timeline = await screen.findByRole("list", { name: "Shipment history" });
    const items = within(timeline).getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(items[0]).toHaveTextContent("Shipping label created");
    expect(items[0]).toHaveTextContent("Rotterdam, NL");
    expect(items[0]).toHaveTextContent("8 Oct 2026, 16:30 UTC");
    expect(items[4]).toHaveTextContent("Departed sorting hub");
    expect(items[4]).toHaveTextContent("Latest");
    expect(screen.getByText("In transit")).toBeVisible();
  });

  it("marks only the newest event as latest", async () => {
    renderApp(fakeService(), "#/parcel/PK1000000003");
    const items = within(await screen.findByRole("list", { name: "Shipment history" })).getAllByRole("listitem");
    expect(items.filter((li) => li.textContent?.includes("Latest"))).toHaveLength(1);
    expect(items.at(-1)).toHaveTextContent("Delivered, signed for by recipient");
    expect(screen.getByText("Delivered", { selector: ".badge span" })).toBeVisible();
  });

  it("announces loading while the parcel is pending", async () => {
    const pending = deferred<Parcel>();
    renderApp(fakeService({ getParcel: () => pending.promise }), "#/parcel/PK1000000001");
    expect(screen.getByRole("status")).toHaveTextContent("Loading parcel");
    expect(screen.getByRole("heading", { level: 1, name: "PK1000000001" })).toBeInTheDocument();

    pending.reject(new ParcelNotFoundError("PK1000000001"));
    await screen.findByText("Parcel not found");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("explains an unknown parcel", async () => {
    renderApp(fakeService(), "#/parcel/PK9999999999");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Parcel not found");
    expect(alert).toHaveTextContent("PK9999999999");
    expect(screen.queryByRole("list", { name: "Shipment history" })).not.toBeInTheDocument();
  });

  it("explains an invalid tracking number and how to write one", async () => {
    renderApp(fakeService(), "#/parcel/hello");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("isn't a valid tracking number");
    expect(alert).toHaveTextContent("PK followed by ten digits");
  });

  it("shows an error with a retry when the service is unavailable", async () => {
    const real = fakeService();
    const getParcel = vi
      .fn<(trackingNumber: string) => Promise<Parcel>>()
      .mockRejectedValueOnce(new CarrierUnavailableError("down"))
      .mockImplementation(real.getParcel);
    renderApp(fakeService({ getParcel }), "#/parcel/PK1000000002");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("We couldn't load this parcel");
    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("list", { name: "Shipment history" })).toBeInTheDocument();
    expect(getParcel).toHaveBeenCalledTimes(2);
  });

  it("treats an unexpected failure like an outage", async () => {
    renderApp(fakeService({ getParcel: () => Promise.reject(new TypeError("boom")) }), "#/parcel/PK1000000001");
    expect(await screen.findByRole("alert")).toHaveTextContent("We couldn't load this parcel");
  });

  it("passes the decoded tracking number to the service", async () => {
    const getParcel = vi.fn().mockRejectedValue(new InvalidTrackingNumberError("PK 1"));
    renderApp(fakeService({ getParcel }), "#/parcel/PK%201");
    await screen.findByRole("alert");
    expect(getParcel).toHaveBeenCalledWith("PK 1");
  });

  it("links back to the search", async () => {
    renderApp(fakeService(), "#/parcel/PK1000000001");
    await screen.findByRole("list", { name: "Shipment history" });
    await userEvent.click(screen.getByRole("link", { name: /Track another parcel/ }));
    expect(await screen.findByRole("heading", { level: 1, name: "Track a parcel" })).toBeInTheDocument();
  });

  it("does not show the previous parcel while the next one loads", async () => {
    const second = deferred<Parcel>();
    const real = fakeService();
    const getParcel = vi.fn((tn: string) => (tn === "PK1000000002" ? second.promise : real.getParcel(tn)));
    renderApp(fakeService({ getParcel }), "#/parcel/PK1000000001");
    await screen.findByRole("list", { name: "Shipment history" });

    window.location.hash = "#/parcel/PK1000000002";
    expect(await screen.findByRole("status")).toHaveTextContent("Loading parcel");
    expect(screen.queryByRole("list", { name: "Shipment history" })).not.toBeInTheDocument();
    second.resolve(await real.getParcel("PK1000000002"));
    await screen.findByRole("list", { name: "Shipment history" });
  });
});

describe("navigation", () => {
  it("moves focus to the page heading after navigating", async () => {
    renderApp(fakeService());
    await userEvent.type(screen.getByLabelText("Tracking number"), "PK1000000001{Enter}");
    const heading = await screen.findByRole("heading", { level: 1, name: "PK1000000001" });
    await waitFor(() => expect(heading).toHaveFocus());
  });

  it("titles the document after the page", async () => {
    renderApp(fakeService());
    await waitFor(() => expect(document.title).toBe("Track a parcel · Parcel Tracker"));
    window.location.hash = "#/parcel/PK1000000001";
    await waitFor(() => expect(document.title).toBe("PK1000000001 · Parcel Tracker"));
  });

  it("says so when the page does not exist", async () => {
    renderApp(fakeService(), "#/nowhere");
    expect(await screen.findByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to the home page" })).toHaveAttribute("href", "#/");
  });

  it("lets keyboard users skip to the content", async () => {
    renderApp(fakeService());
    await userEvent.tab();
    const skip = screen.getByRole("link", { name: "Skip to content" });
    expect(skip).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByRole("main")).toHaveFocus();
    expect(window.location.hash).toBe("#/");
    await screen.findByRole("table");
  });
});
