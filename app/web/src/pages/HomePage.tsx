import { useCallback } from "react";
import { ErrorNotice, EmptyState, Loading } from "../components/Feedback";
import { ParcelTable } from "../components/ParcelTable";
import { SearchForm } from "../components/SearchForm";
import { goToParcel } from "../router";
import { useParcelService } from "../service-context";
import { useDocumentTitle } from "../useDocumentTitle";
import { useRemote } from "../useRemote";

export function HomePage() {
  const service = useParcelService();
  const load = useCallback(() => service.listParcels(), [service]);
  const { state, retry } = useRemote(load);
  useDocumentTitle("Track your parcel");

  return (
    <>
      <section className="hero" aria-labelledby="page-title">
        <h1 id="page-title" tabIndex={-1}>
          Track your parcel
        </h1>
        <p className="lead">See where your parcel is, where it has been and what happens next.</p>
        <SearchForm onSearch={goToParcel} />
      </section>

      <section className="recent" aria-labelledby="recent-heading">
        <h2 id="recent-heading">Recent parcels</h2>
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
          <ParcelTable parcels={state.data} labelledBy="recent-heading" />
        )}
      </section>
    </>
  );
}
