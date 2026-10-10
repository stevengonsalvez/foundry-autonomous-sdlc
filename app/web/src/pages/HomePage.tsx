import React from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ParcelTable } from "../components/ParcelTable";
import { useParcelService } from "../service-context";

const STATUSES = ["label_created", "in_transit", "out_for_delivery", "delivered", "exception"] as const;
export type Status = typeof STATUSES[number];

export function HomePage() {
  const service = useParcelService();
  const [searchParams, setSearchParams] = useSearchParams();
  const status = searchParams.get("status");

  const allParcels = service.listParcels();

  const validStatus = STATUSES.includes(status as Status) ? (status as Status) : null;

  const parcels = validStatus ? allParcels.filter((p) => p.status === validStatus) : allParcels;

  function onChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const value = e.target.value;
    if (value === "") {
      searchParams.delete("status");
      setSearchParams(searchParams);
    } else {
      searchParams.set("status", value);
      setSearchParams(searchParams);
    }
  }

  return (
    <main>
      <h1>Parcels</h1>
      <label htmlFor="status-filter">Filter by status</label>
      <select id="status-filter" value={validStatus ?? ""} onChange={onChange}>
        <option value="">(all)</option>
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>

      {parcels.length === 0 ? (
        <p>No parcels match this status.</p>
      ) : (
        <ParcelTable parcels={parcels} />
      )}

      <p>
        <Link to="/">Refresh</Link>
      </p>
    </main>
  );
}

export default HomePage;
