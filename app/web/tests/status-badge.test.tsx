import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PARCEL_STATUSES, type ParcelStatus } from "@parcel/core";
import { StatusBadge } from "../src/components/StatusBadge";

const LABELS: Record<ParcelStatus, string> = {
  label_created: "Label created",
  in_transit: "In transit",
  out_for_delivery: "Out for delivery",
  delivered: "Delivered",
  exception: "Exception",
};

describe("StatusBadge", () => {
  it.each(PARCEL_STATUSES)("says %s in words, not only in colour", (status) => {
    const { container } = render(<StatusBadge status={status} />);
    expect(screen.getByText(LABELS[status])).toBeVisible();
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });
});
