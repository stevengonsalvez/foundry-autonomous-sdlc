import { useCallback } from "react";
import { PARCEL_STATUSES, type ParcelStatus } from "@parcel/core";
import { ErrorNotice, EmptyState, Loading } from "../components/Feedback";
import { ParcelTable } from "../components/ParcelTable";
import { SearchForm } from "../components/SearchForm";
import { STATUS_LABELS, StatusBadge } from "../components/StatusBadge";
import { goToHome, goToParcel, parseStatusFilter, useHash } from "../router";
import { useParcelService } from "../service-context";
import { useDocumentTitle } from "../useDocumentTitle";
import { useRemote } from "../useRemote";

export function HomePage() {
  const service = useParcelService();
  const load = useCallback(() => service.listParcels(), [service]);
  const { state, retry } = useRemote(load);
  const hash = useHash();
  const statusFilter = parseStatusFilter(hash);
  useDocumentTitle("Track a parcel");

  const filteredParcels =
    state.status === "success"
      ? statusFilter === "all"
        ? state.data
        : state.data.filter((p) => p.status === statusFilter)
      : [];

  return (
    <>
      <section className="hero" aria-labelledby="page-title">
        <h1 id="page-title" tabIndex={-1}>
          Track a parcel
        </h1>
        <p className="lead">See where your parcel is, where it has been and what happens next.</p>
        <SearchForm onSearch={goToParcel} showRecentSearches />
      </section>

      <section id="recent" className="recent" aria-labelledby="recent-heading">
        <div className="recent__header">
          <h2 id="recent-heading">Recent parcels</h2>
          {state.status === "success" && state.data.length > 0 && (
            <div className="status-filter">
              <label htmlFor="status-filter">Filter by status</label>
              <select
                id="status-filter"
                name="status"
                value={statusFilter}
                onChange={(e) => goToHome(e.target.value as ParcelStatus | "all")}
              >
                <option value="all">All statuses</option>
                {PARCEL_STATUSES.map((status) => (
                  <option key={status} value={status}>
                    {STATUS_LABELS[status]}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
        {state.status === "loading" && <Loading label="Loading recent parcels" rows={4} />}
        {state.status === "error" && (
          <ErrorNotice title="We couldn't load recent parcels" onRetry={retry}>
            Something went wrong on our side. Please try again in a moment.
          </ErrorNotice>
        )}
        {state.status === "success" && state.data.length === 0 && (
          <EmptyState title="No parcels yet">Parcels will appear here as soon as the carrier reports them.</EmptyState>
        )}
        {state.status === "success" && state.data.length > 0 && (
          filteredParcels.length > 0 ? (
            <ParcelTable parcels={filteredParcels} labelledBy="recent-heading" />
          ) : (
            <p className="notice notice--empty">No parcels match this status.</p>
          )
        )}
      </section>

      <section id="status-guide" className="status-guide" aria-labelledby="status-guide-heading">
        <div className="status-guide__header">
          <h2 id="status-guide-heading">Status guide</h2>
          <p className="lead">Understand what each shipment status means for your parcel.</p>
        </div>
        <div className="status-guide__grid">
          <div className="status-guide__card">
            <StatusBadge status="label_created" />
            <p className="status-guide__desc">The carrier has received shipment details and is waiting for the parcel.</p>
          </div>
          <div className="status-guide__card">
            <StatusBadge status="in_transit" />
            <p className="status-guide__desc">The parcel is moving through the carrier network toward its destination.</p>
          </div>
          <div className="status-guide__card">
            <StatusBadge status="out_for_delivery" />
            <p className="status-guide__desc">The parcel is on the local delivery vehicle and scheduled for delivery today.</p>
          </div>
          <div className="status-guide__card">
            <StatusBadge status="delivered" />
            <p className="status-guide__desc">The parcel has been successfully delivered to the recipient address.</p>
          </div>
          <div className="status-guide__card">
            <StatusBadge status="exception" />
            <p className="status-guide__desc">An unexpected event or delay occurred during transit.</p>
          </div>
        </div>
      </section>
    </>
  );
}
