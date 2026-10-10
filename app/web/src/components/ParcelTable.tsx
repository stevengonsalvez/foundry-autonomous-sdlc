import type { ParcelSummary } from "@parcel/core";
import { formatDateTime } from "../format";
import { parcelHref } from "../router";
import { StatusBadge } from "./StatusBadge";

export function ParcelTable({ parcels, labelledBy }: { parcels: ParcelSummary[]; labelledBy: string }) {
  return (
    <table className="parcel-table" aria-labelledby={labelledBy}>
      <thead>
        <tr>
          <th scope="col">Tracking number</th>
          <th scope="col">Status</th>
          <th scope="col">Last update</th>
        </tr>
      </thead>
      <tbody>
        {parcels.map((parcel) => (
          <tr key={parcel.trackingNumber}>
            <td data-label="Tracking number">
              <a href={parcelHref(parcel.trackingNumber)} className="mono">
                {parcel.trackingNumber}
              </a>
            </td>
            <td data-label="Status">
              <StatusBadge status={parcel.status} />
            </td>
            <td data-label="Last update">
              <time dateTime={parcel.lastUpdate}>{formatDateTime(parcel.lastUpdate)}</time>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
