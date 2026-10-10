import { useCallback } from "react";
import { InvalidTrackingNumberError, ParcelNotFoundError } from "@parcel/core";
import { ArrowLeftIcon } from "../components/Icons";
import { ErrorNotice, Loading } from "../components/Feedback";
import { StatusBadge } from "../components/StatusBadge";
import { Timeline } from "../components/Timeline";
import { HOME_HREF } from "../router";
import { useParcelService } from "../service-context";
import { useDocumentTitle } from "../useDocumentTitle";
import { useRemote } from "../useRemote";
import { formatEstimatedDelivery } from "../format";

function ParcelError({ error, trackingNumber, onRetry }: { error: unknown; trackingNumber: string; onRetry: () => void }) {
  if (error instanceof InvalidTrackingNumberError) {
    return (
      <ErrorNotice level={2} title="That isn't a valid tracking number">
        Tracking numbers start with PK followed by ten digits, for example <span className="mono">PK1000000001</span>.
      </ErrorNotice>
    );
  }
  if (error instanceof ParcelNotFoundError) {
    return (
      <ErrorNotice level={2} title="Parcel not found">
        We have no parcel with the tracking number <span className="mono">{trackingNumber}</span>. Check the number and
        try again.
      </ErrorNotice>
    );
  }
  return (
    <ErrorNotice level={2} title="We couldn't load this parcel" onRetry={onRetry}>
      Something went wrong on our side. Please try again in a moment.
    </ErrorNotice>
  );
}

export function ParcelPage({ trackingNumber }: { trackingNumber: string }) {
  const service = useParcelService();
  const load = useCallback(() => service.getParcel(trackingNumber), [service, trackingNumber]);
  const { state, retry } = useRemote(load);
  useDocumentTitle(trackingNumber);

  return (
    <>
      <a className="back-link" href={HOME_HREF}>
        <ArrowLeftIcon />
        Track another parcel
      </a>

      <header className="parcel-header">
        <p className="eyebrow">Tracking number</p>
        <div className="parcel-header__row">
          <h1 id="page-title" className="mono" tabIndex={-1}>
            {trackingNumber}
          </h1>
          {state.status === "success" && <StatusBadge status={state.data.status} />}
        </div>
        {state.status === "success" &&
          (state.data.status === "label_created" ||
            state.data.status === "in_transit" ||
            state.data.status === "out_for_delivery") &&
          Boolean(state.data.estimatedDelivery) && (
            <p className="parcel-header__delivery">
              Estimated delivery: {formatEstimatedDelivery(state.data.estimatedDelivery as string)}
            </p>
          )}
      </header>

      {state.status === "loading" && <Loading label="Loading parcel" rows={4} />}
      {state.status === "error" && <ParcelError error={state.error} trackingNumber={trackingNumber} onRetry={retry} />}
      {state.status === "success" && (
        <section className="card" aria-labelledby="timeline-heading">
          <h2 id="timeline-heading">Shipment history</h2>
          <Timeline events={state.data.events} labelledBy="timeline-heading" />
        </section>
      )}
    </>
  );
}
