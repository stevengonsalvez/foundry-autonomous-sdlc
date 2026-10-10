import { useMemo } from "react";
import { Link } from "react-router-dom";
import { ParcelTable } from "../components/ParcelTable";
import { SearchForm } from "../components/SearchForm";
import { useService } from "../service-context";
import { useSearchParams } from "react-router-dom";

const STATUSES = ["label_created", "in_transit", "exception", "delivered"] as const;
export type ParcelStatus = typeof STATUSES[number];

export function HomePage() {
  const service = useService();
  const [params, setParams] = useSearchParams();

  const statusParam = params.get("status") ?? "";
  const validStatus = STATUSES.includes(statusParam as ParcelStatus) ? (statusParam as ParcelStatus) : "";

  const { parcels } = service.useListParcels();

  const filtered = useMemo(() => {
    if (!validStatus) return parcels;
    return parcels.filter((p) => p.status === validStatus);
  }, [parcels, validStatus]);

  function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const v = e.target.value;
    if (v) {
      params.set("status", v);
    } else {
      params.delete("status");
    }
    setParams(params);
  }

  return (
    <main className="container" id="main-content" tabIndex={-1}>
      <section aria-labelledby="page-title" className="hero">
        <h1 id="page-title" tabIndex={-1}>Track your parcel</h1>
        <p className="lead">See where your parcel is, where it has been and what happens next.</p>
        <SearchForm />
      </section>

      <section aria-labelledby="recent-heading" className="recent">
        <h2 id="recent-heading">Recent parcels</h2>

        <label htmlFor="filter-status">Filter by status</label>
        <div style={{ marginBottom: "1rem" }}>
          <select id="filter-status" value={validStatus} onChange={handleChange}>
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.replace("_", " ")}
              </option>
            ))}
          </select>
        </div>

        {filtered.length === 0 ? (
          <p>No parcels match this status.</p>
        ) : (
          <ParcelTable parcels={filtered} ariaLabelledBy="recent-heading" />
        )}

        <p>
          <Link to="/">View all</Link>
        </p>
      </section>
    </main>
  );
}
