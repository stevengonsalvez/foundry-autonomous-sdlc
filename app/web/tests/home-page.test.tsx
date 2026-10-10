import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CarrierUnavailableError, type ParcelSummary } from "@parcel/core";
import { deferred, fakeService, renderApp } from "./helpers";

describe("home page", () => {
  it("greets with the Track a parcel heading", async () => {
    renderApp(fakeService());
    expect(screen.getByRole("heading", { level: 1, name: "Track a parcel" })).toBeInTheDocument();
    await screen.findByRole("table");
  });

  it("offers a labelled tracking number field and a Track button", async () => {
    renderApp(fakeService());
    expect(screen.getByLabelText("Tracking number")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Track" })).toBeInTheDocument();
    expect(screen.getByRole("search")).toBeInTheDocument();
    await screen.findByRole("table");
  });

  it("has banner, main and contentinfo landmarks", async () => {
    renderApp(fakeService());
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
    await screen.findByRole("table");
  });

  it("lists recent parcels, newest update first, with status badges", async () => {
    renderApp(fakeService());
    const table = await screen.findByRole("table", { name: "Recent parcels" });
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Tracking number",
      "Status",
      "Last update",
    ]);
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(8);

    const first = within(rows[0]!);
    expect(first.getByRole("link", { name: "PK1000000004" })).toHaveAttribute("href", "#/parcel/PK1000000004");
    expect(first.getByText("Label created")).toBeVisible();
    expect(first.getByText("10 Oct 2026, 09:12 UTC")).toBeInTheDocument();

    expect(within(rows[1]!).getByRole("link")).toHaveTextContent("PK1000000002");
    expect(within(rows[1]!).getByText("Out for delivery")).toBeVisible();
  });

  it("announces loading while the list is pending", async () => {
    const pending = deferred<ParcelSummary[]>();
    renderApp(fakeService({ listParcels: () => pending.promise }));
    expect(screen.getByRole("status")).toHaveTextContent("Loading recent parcels");
    pending.resolve([]);
    await screen.findByText("No parcels yet");
  });

  it("explains an empty list", async () => {
    renderApp(fakeService({ listParcels: async () => [] }));
    expect(await screen.findByText("No parcels yet")).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows an error with a retry that reloads the list", async () => {
    const real = fakeService();
    const listParcels = vi
      .fn<() => Promise<ParcelSummary[]>>()
      .mockRejectedValueOnce(new CarrierUnavailableError("down"))
      .mockImplementation(real.listParcels);
    renderApp(fakeService({ listParcels }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("We couldn't load recent parcels");
    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(listParcels).toHaveBeenCalledTimes(2);
  });

  it("opens the parcel page when a recent parcel is clicked", async () => {
    renderApp(fakeService());
    await userEvent.click(await screen.findByRole("link", { name: "PK1000000003" }));
    expect(await screen.findByRole("heading", { level: 1, name: "PK1000000003" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/parcel/PK1000000003");
  });
});

describe("search form", () => {
  it("navigates to the parcel page and shows its timeline", async () => {
    renderApp(fakeService());
    await userEvent.type(screen.getByLabelText("Tracking number"), "PK1000000001");
    await userEvent.click(screen.getByRole("button", { name: "Track" }));

    expect(await screen.findByRole("heading", { level: 1, name: "PK1000000001" })).toBeInTheDocument();
    expect(await screen.findByRole("list", { name: "Shipment history" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/parcel/PK1000000001");
  });

  it("submits with Enter and ignores surrounding spaces", async () => {
    renderApp(fakeService());
    await userEvent.type(screen.getByLabelText("Tracking number"), "  PK1000000002  {Enter}");
    expect(await screen.findByRole("heading", { level: 1, name: "PK1000000002" })).toBeInTheDocument();
  });

  it("asks for a number instead of navigating when the field is empty", async () => {
    renderApp(fakeService());
    await userEvent.click(screen.getByRole("button", { name: "Track" }));

    const input = screen.getByLabelText("Tracking number");
    expect(screen.getByText("Enter a tracking number")).toBeVisible();
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription(expect.stringContaining("Enter a tracking number"));
    expect(input).toHaveFocus();
    expect(window.location.hash).toBe("#/");
    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
  });

  it("clears the complaint once the user types", async () => {
    renderApp(fakeService());
    await userEvent.click(screen.getByRole("button", { name: "Track" }));
    await userEvent.type(screen.getByLabelText("Tracking number"), "P");
    expect(screen.queryByText("Enter a tracking number")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Tracking number")).not.toHaveAttribute("aria-invalid", "true");
    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
  });
});
