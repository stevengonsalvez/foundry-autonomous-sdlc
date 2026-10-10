import React from "react";
import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { useRemote } from "../useRemote";
import { parcelService } from "../http-parcel-service";
import { StatusBadge } from "../components/StatusBadge";
import { Timeline } from "../components/Timeline";
import { formatDateTime } from "../format";

export default function ParcelPage() {
  const { id } = useParams();
  const remote = useRemote(() => parcelService.getParcel(id ?? ""), [id]);

  useEffect(() => {
    // noop
  }, [remote]);

  if (remote.loading) return <div>Loading…</div>;
  if (remote.error) return <div>Error</div>;
  if (!remote.data) return <div>Not found</div>;

  const p = remote.data;

  const showEstimate = p.estimatedDelivery && ["label_created", "in_transit", "out_for_delivery"].includes(p.status);

  return (
    <main>
      <section aria-labelledby="summary">
        <h1 id="summary">Parcel {p.trackingNumber}</h1>
        <StatusBadge status={p.status} />
        {showEstimate ? <div>Estimated delivery: {formatDateTime(p.estimatedDelivery)}</div> : null}
        <dl>
          <dt>Last update</dt>
          <dd>{p.lastUpdate}</dd>
        </dl>
      </section>

      <section aria-labelledby="timeline">
        <h2 id="timeline">Timeline</h2>
        <Timeline events={p.events} />
      </section>
    </main>
  );
}
