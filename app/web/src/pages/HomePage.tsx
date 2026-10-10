import React from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import { ParcelTable } from "../components/ParcelTable";
import { useService } from "../service-context";

function useQuery() {
  const { search } = useLocation();
  return useMemo(() => new URLSearchParams(search), [search]);
}

export const HomePage: React.FC = () => {
  const service = useService();
  const navigate = useNavigate();
  const query = useQuery();
  const [parcels, setParcels] = useState([] as any[]);
  const [statusFilter, setStatusFilter] = useState<string | undefined>(() => query.get("status") ?? undefined);

  useEffect(() => {
    let mounted = true;
    service.listParcels().then((p) => {
      if (mounted) setParcels(p);
    });
    return () => {
      mounted = false;
    };
  }, [service]);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (statusFilter) params.set("status", statusFilter);
    else params.delete("status");
    navigate({ search: params.toString() ? `?${params.toString()}` : "" }, { replace: true });
  }, [statusFilter, navigate]);

  const statuses = Array.from(new Set(parcels.map((p) => p.status))).sort();

  const filtered = useMemo(() => {
    if (!statusFilter) return parcels;
    return parcels.filter((p) => p.status === statusFilter);
  }, [parcels, statusFilter]);

  return (
    <div>
      <h1>Parcel Tracker</h1>
      <label htmlFor="status-filter">Filter by status</label>
      <select
        id="status-filter"
        value={statusFilter ?? ""}
        onChange={(e) => setStatusFilter(e.target.value || undefined)}
        data-testid="status-select"
      >
        <option value="">All</option>
        {statuses.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      {filtered.length === 0 ? (
        <p>No parcels match this status.</p>
      ) : (
        <ParcelTable parcels={filtered} />
      )}
      <p>
        <Link to="/parcel/PK1000000001">Example parcel</Link>
      </p>
    </div>
  );
};
