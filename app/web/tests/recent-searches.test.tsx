import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { TrackingNumber } from "@parcel/core";
import { fakeService, renderApp } from "./helpers";

describe("recent searches", () => {
  it("stores successful searches in localStorage under the recent_searches key, newest first and capped at 5 unique items", async () => {
    renderApp(fakeService());

    const numbers = [
      "PK1000000001",
      "PK1000000002",
      "PK1000000003",
      "PK1000000004",
      "PK1000000005",
      "PK1000000006",
    ] as TrackingNumber[];

    // perform six searches; the stored list should keep the newest five, newest first
    for (const n of numbers) {
      await userEvent.type(screen.getByLabelText("Tracking number"), n);
      await userEvent.click(screen.getByRole("button", { name: "Track" }));
    }

    const raw = window.localStorage.getItem("recent_searches");
    expect(raw).not.toBeNull();

    const parsed = JSON.parse(raw ?? "null");
    // newest first and only last five unique entries
    expect(parsed).toEqual([
      "PK1000000006",
      "PK1000000005",
      "PK1000000004",
      "PK1000000003",
      "PK1000000002",
    ]);
  });

  it("shows recent search chips on the home page, navigates when a chip is clicked, and clear history removes them", async () => {
    // pre-populate localStorage with two searches
    const entries = ["PK1000000001", "PK1000000002"];
    window.localStorage.setItem("recent_searches", JSON.stringify(entries));

    renderApp(fakeService());

    // the home page should show a list of recent searches (chips)
    const list = await screen.findByRole("list", { name: "Recent searches" });
    // chips should be buttons with the tracking numbers
    const chip1 = await screen.findByRole("button", { name: "PK1000000001" });
    const chip2 = await screen.findByRole("button", { name: "PK1000000002" });
    expect(list).toBeInTheDocument();
    expect(chip1).toBeInTheDocument();
    expect(chip2).toBeInTheDocument();

    // clicking a chip navigates to that parcel page immediately
    await userEvent.click(chip2);
    expect(await screen.findByRole("heading", { level: 1, name: "PK1000000002" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/parcel/PK1000000002");

    // return to home and clear history
    renderApp(fakeService());
    const clear = await screen.findByRole("button", { name: "Clear history" });
    await userEvent.click(clear);

    // localStorage should no longer have the key and chips should be hidden
    expect(window.localStorage.getItem("recent_searches")).toBeNull();
    expect(screen.queryByRole("list", { name: "Recent searches" })).not.toBeInTheDocument();
  });
});