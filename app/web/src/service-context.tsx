import { createContext, useContext } from "react";
import type { ParcelService } from "@parcel/core";

export const ServiceContext = createContext<ParcelService | null>(null);

export function useParcelService(): ParcelService {
  const service = useContext(ServiceContext);
  if (!service) throw new Error("useParcelService must be used inside <App>");
  return service;
}
