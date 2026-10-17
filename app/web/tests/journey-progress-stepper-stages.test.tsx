import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { fakeService, renderApp } from "./helpers";

describe("journey progress stepper - completed checkmarks and active styling", () => {
  it("completed stages receive checkmark indicators observable in the DOM", async () => {
    // PK1000000001 is in_transit: 'Label created' is completed, 'In transit' is active
    renderApp(fakeService(), "#/parcel/PK1000000001");

    const stepper = await screen.findByTestId("journey-progress-stepper");
    expect(stepper).toBeInTheDocument();

    const labelCreatedStep = stepper.querySelector('[data-stage="label_created"]');
    expect(labelCreatedStep).toBeInTheDocument();
    expect(labelCreatedStep).toHaveAttribute("data-step-state", "completed");
    expect(labelCreatedStep).toHaveAttribute("data-completed", "true");
    expect(labelCreatedStep?.classList.contains("is-completed")).toBe(true);

    const checkmark = within(labelCreatedStep as HTMLElement).getByTestId("step-checkmark");
    expect(checkmark).toBeInTheDocument();
    expect(checkmark.querySelector("svg")).toBeInTheDocument();

    // Upcoming stages do not have checkmarks
    const outForDeliveryStep = stepper.querySelector('[data-stage="out_for_delivery"]');
    expect(within(outForDeliveryStep as HTMLElement).queryByTestId("step-checkmark")).not.toBeInTheDocument();
  });

  it("current active stage receives highlighted focus styling and observable active attributes", async () => {
    // PK1000000001 is in_transit: 'In transit' is the current active stage
    renderApp(fakeService(), "#/parcel/PK1000000001");

    const stepper = await screen.findByTestId("journey-progress-stepper");
    const activeStep = stepper.querySelector('[data-step-state="active"]');
    expect(activeStep).toBeInTheDocument();
    expect(activeStep).toHaveAttribute("data-stage", "in_transit");
    expect(activeStep).toHaveAttribute("data-active", "true");
    expect(activeStep).toHaveAttribute("aria-current", "step");
    expect(activeStep?.classList.contains("is-active")).toBe(true);
    expect(activeStep?.classList.contains("progress-stepper__step--active")).toBe(true);
  });

  it("all sequential completed stages show checkmark indicators when parcel is delivered", async () => {
    // PK1000000003 is DELIVERED fixture: all stages are completed
    renderApp(fakeService(), "#/parcel/PK1000000003");

    const stepper = await screen.findByTestId("journey-progress-stepper");
    const checkmarks = stepper.querySelectorAll('[data-testid="step-checkmark"]');
    expect(checkmarks).toHaveLength(4);

    const steps = stepper.querySelectorAll(".progress-stepper__step");
    expect(steps).toHaveLength(4);
    for (const step of steps) {
      expect(step).toHaveAttribute("data-step-state", "completed");
      expect(step).toHaveAttribute("data-completed", "true");
      expect(step.classList.contains("is-completed")).toBe(true);
    }
  });

  it("advances active stage and checkmark indicators as shipment progresses to out for delivery", async () => {
    // PK1000000002 is out_for_delivery: Label created and In transit completed, Out for delivery active
    renderApp(fakeService(), "#/parcel/PK1000000002");

    const stepper = await screen.findByTestId("journey-progress-stepper");
    const checkmarks = stepper.querySelectorAll('[data-testid="step-checkmark"]');
    expect(checkmarks).toHaveLength(2);

    const labelCreated = stepper.querySelector('[data-stage="label_created"]');
    expect(labelCreated).toHaveAttribute("data-step-state", "completed");

    const inTransit = stepper.querySelector('[data-stage="in_transit"]');
    expect(inTransit).toHaveAttribute("data-step-state", "completed");

    const outForDelivery = stepper.querySelector('[data-stage="out_for_delivery"]');
    expect(outForDelivery).toHaveAttribute("data-step-state", "active");
    expect(outForDelivery).toHaveAttribute("data-active", "true");
    expect(outForDelivery).toHaveAttribute("aria-current", "step");
    expect(outForDelivery?.classList.contains("is-active")).toBe(true);
  });
});
