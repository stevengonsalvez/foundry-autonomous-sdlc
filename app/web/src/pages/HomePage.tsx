import React from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useParcels } from "../service-context";
import ParcelTable from "../components/ParcelTable";

const statuses = ["all", "label_created", "in_transit", "delivered", "exception"] as const;
export type Status = (typeof statuses)[number];

export default function HomePage() {
  const { parcels } = useParcels();
  const [searchParams, setSearchParams] = useSearchParams();

  const status = (searchParams.get("status") as Status) ?? "all";
  const valid = statuses.includes(status);
  const filtered = !valid || status === "all" ? parcels : parcels.filter((p) => p.status === status);

  function apply(s: string) {
    const params = new URLSearchParams(searchParams);
    if (s === "all") params.delete("status");
    else params.set("status", s);
    setSearchParams(params);
  }

  return (
    <main>
      <h1>Parcels</h1>
      <label htmlFor="status-filter">Filter by status</label>
      <select
        id="status-filter"
        value={valid ? status : "all"}
        onChange={(e) => apply(e.target.value)}
        aria-label="Filter by status"
      >
        {statuses.map((s) => (
          <option key={s} value={s}>
            {s === "all" ? "All" : s.replace(/_/g, " ")}
          </option>
        ))}
      </select>

      {filtered.length === 0 ? (
        <p>No parcels match this status.</p>
      ) : (
        <ParcelTable parcels={filtered} />
      )}

      <p>
        <Link to="/">Back to list</Link>
      </p>
    </main>
  );
}
