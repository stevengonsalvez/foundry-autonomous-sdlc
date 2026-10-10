import { useCallback } from "react";
import { PARCEL_STATUSES, type ParcelStatus } from "@parcel/core";
import { ErrorNotice, EmptyState, Loading } from "../components/Feedback";
import { ParcelTable } from "../components/ParcelTable";
import { SearchForm } from "../components/SearchForm";
import { STATUS_LABELS } from "../components/StatusBadge";
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
        <SearchForm onSearch={goToParcel} />
      </section>

      <section className="recent" aria-labelledby="recent-heading">
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
    </>
  );
}
