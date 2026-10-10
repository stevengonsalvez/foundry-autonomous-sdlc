import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it } from "vitest";
import { fakeService, renderApp } from "./helpers";

describe("tracking number input case insensitivity", () => {
  it("accepts a fully lowercase tracking number and navigates to the same parcel page as the uppercase form", async () => {
    renderApp(fakeService());
    await userEvent.type(screen.getByLabelText("Tracking number"), "pk1000000001");
    await userEvent.click(screen.getByRole("button", { name: "Track" }));

    // Expect the app to normalise and show the uppercase form
    expect(await screen.findByRole("heading", { level: 1, name: "PK1000000001" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/parcel/PK1000000001");
  });

  it("accepts a mixed-case tracking number and treats it identically to the uppercase form", async () => {
    renderApp(fakeService());
    await userEvent.type(screen.getByLabelText("Tracking number"), "Pk1000000001");
    await userEvent.click(screen.getByRole("button", { name: "Track" }));

    expect(await screen.findByRole("heading", { level: 1, name: "PK1000000001" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/parcel/PK1000000001");
  });
});
