import type { ParcelStatus } from "@parcel/core";
import { StatusIcon } from "./Icons";

export const STATUS_LABELS: Record<ParcelStatus, string> = {
  label_created: "Label created",
  in_transit: "In transit",
  out_for_delivery: "Out for delivery",
  delivered: "Delivered",
  exception: "Exception",
};

export function StatusBadge({ status }: { status: ParcelStatus }) {
  return (
    <span className={`badge badge--${status}`}>
      <StatusIcon status={status} />
      <span>{STATUS_LABELS[status]}</span>
    </span>
  );
}
