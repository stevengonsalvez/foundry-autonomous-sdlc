import React from "react";
import { useParams } from "react-router-dom";
import { useRemote } from "../useRemote";
import { getParcel } from "../http-parcel-service";
import Timeline from "../components/Timeline";
import StatusBadge from "../components/StatusBadge";
import { formatDate } from "../format";

export default function ParcelPage() {
  const { id } = useParams();
  const { loading, error, value: parcel } = useRemote(() => (id ? getParcel(id) : Promise.resolve(null)), [id]);

  return (
    <main>
      <header className="parcel-header">
        <p className="eyebrow">Tracking number</p>
        <div className="parcel-header__row">
          <h1 className="mono" id="page-title" tabIndex={-1}>
            {parcel?.trackingNumber ?? (loading ? "Loading…" : "")}
          </h1>
          {parcel && <StatusBadge status={parcel.status} />}
        </div>
        {/* Show estimated delivery directly below the status badge when appropriate */}
        {parcel && parcel.estimatedDelivery &&
          (parcel.status === "label_created" || parcel.status === "in_transit" || parcel.status === "out_for_delivery") && (
            <p aria-live="polite">Estimated delivery: {formatDate(parcel.estimatedDelivery)}</p>
          )}
      </header>

      <section aria-label="parcel-summary">
        {loading && <p>Loading…</p>}
        {error && <p role="alert">Error loading parcel</p>}
        {parcel && <Timeline events={parcel.events} />}
      </section>
    </main>
  );
}
