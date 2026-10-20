import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { fakeService, renderApp } from "./helpers";

describe("journey progress stepper", () => {
  it('renders a horizontal milestone progress stepper with data-testid="journey-progress-stepper" and role="progressbar" above the shipment history', async () => {
    renderApp(fakeService(), "#/parcel/PK1000000001");

    const stepper = await screen.findByTestId("journey-progress-stepper");
    expect(stepper).toBeInTheDocument();
    expect(stepper).toHaveAttribute("role", "progressbar");

    const timeline = await screen.findByRole("list", { name: "Shipment history" });
    // Ensure the stepper appears before the shipment history in document order.
    // Node.DOCUMENT_POSITION_FOLLOWING === 4
    // stepper.compareDocumentPosition(timeline) & 4 === 4 means timeline is following stepper
    expect(stepper.compareDocumentPosition(timeline) & 4).toBe(4);
  });

  it('displays four sequential stages labeled: "Label created", "In transit", "Out for delivery", and "Delivered"', async () => {
    renderApp(fakeService(), "#/parcel/PK1000000001");

    const stepper = await screen.findByTestId("journey-progress-stepper");
    const withinStepper = within(stepper);

    expect(withinStepper.getByText("Label created")).toBeInTheDocument();
    expect(withinStepper.getByText("In transit")).toBeInTheDocument();
    expect(withinStepper.getByText("Out for delivery")).toBeInTheDocument();
    expect(withinStepper.getByText("Delivered")).toBeInTheDocument();
  });

  it('when status is exception the active step renders an exception alert styling with data-step-state="exception"', async () => {
    // PK1000000005 is an EXCEPTION fixture in the sample shipments
    renderApp(fakeService(), "#/parcel/PK1000000005");

    const stepper = await screen.findByTestId("journey-progress-stepper");
    // The active step for an exception parcel should include the data-step-state="exception" attribute
    const exceptionStep = stepper.querySelector('[data-step-state="exception"]');
    expect(exceptionStep).toBeInTheDocument();
  });
});