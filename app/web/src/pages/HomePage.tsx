import { useCallback } from "react";
import { PARCEL_STATUSES, type ParcelStatus } from "@parcel/core";
import { ErrorNotice, EmptyState, Loading } from "../components/Feedback";
import { ParcelTable } from "../components/ParcelTable";
import { SearchForm } from "../components/SearchForm";
import { StatusBadge, STATUS_LABELS } from "../components/StatusBadge";
import { StatusSummaryChips } from "../components/StatusSummaryChips";
import { goToHome, goToParcel, parseStatusFilter, useHash } from "../router";
import { useParcelService } from "../service-context";
import { useDocumentTitle } from "../useDocumentTitle";
import { useRemote } from "../useRemote";

const STATUS_GUIDE_ITEMS: Array<{ status: ParcelStatus; description: string }> = [
  {
    status: "label_created",
    description: "The sender created the shipping label and carrier pickup is pending.",
  },
  {
    status: "in_transit",
    description: "The parcel is moving between distribution centers and carrier facilities.",
  },
  {
    status: "out_for_delivery",
    description: "The parcel has reached the local delivery depot and is out with the courier.",
  },
  {
    status: "delivered",
    description: "The parcel has arrived at the destination address or safe place.",
  },
  {
    status: "exception",
    description: "An unexpected event or delivery issue occurred, such as weather delay or incorrect address.",
  },
];

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
                <option value="all">All parcels</option>
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
          <>
            <StatusSummaryChips
              parcels={state.data}
              selectedStatus={statusFilter}
              onSelect={goToHome}
            />
            {filteredParcels.length > 0 ? (
              <ParcelTable parcels={filteredParcels} labelledBy="recent-heading" />
            ) : (
              <p className="notice notice--empty">No parcels match this status.</p>
            )}
          </>
        )}
      </section>

      <section id="status-guide" className="status-guide" aria-labelledby="status-guide-heading">
        <h2 id="status-guide-heading">Status guide</h2>
        <p className="lead">Understand what each parcel status means during delivery.</p>
        <div className="status-guide__grid">
          {STATUS_GUIDE_ITEMS.map(({ status, description }) => (
            <div key={status} className="status-guide__card">
              <div className="status-guide__badge">
                <StatusBadge status={status} />
              </div>
              <p className="status-guide__desc">{description}</p>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
