import { useSyncExternalStore } from "react";
import { PARCEL_STATUSES, type ParcelStatus } from "@parcel/core";

export type Route =
  | { name: "home" }
  | { name: "parcel"; trackingNumber: string }
  | { name: "unknown" };

function decode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

export function parseRoute(hash: string): Route {
  const raw = hash.replace(/^#/, "");
  const path = raw.split("?")[0] ?? "";
  if (
    path === "" ||
    path === "/" ||
    path === "recent" ||
    path === "/recent" ||
    path === "status-guide" ||
    path === "/status-guide"
  ) {
    return { name: "home" };
  }
  const match = /^\/parcel\/([^/]+)$/.exec(path);
  return match ? { name: "parcel", trackingNumber: decode(match[1] ?? "") } : { name: "unknown" };
}

function isParcelStatus(value: string): value is ParcelStatus {
  return (PARCEL_STATUSES as readonly string[]).includes(value);
}

export function parseStatusFilter(hash: string): ParcelStatus | "all" {
  const queryIndex = hash.indexOf("?");
  if (queryIndex === -1) return "all";
  const params = new URLSearchParams(hash.slice(queryIndex + 1));
  const status = params.get("status");
  return status && isParcelStatus(status) ? status : "all";
}

export const HOME_HREF = "#/";

export function homeHref(status?: ParcelStatus | "all"): string {
  if (!status || status === "all") {
    return HOME_HREF;
  }
  return `#/?status=${encodeURIComponent(status)}`;
}

export function goToHome(status?: ParcelStatus | "all"): void {
  window.location.hash = homeHref(status);
}

export function parcelHref(trackingNumber: string): string {
  return `#/parcel/${encodeURIComponent(trackingNumber)}`;
}

export function goToParcel(trackingNumber: string): void {
  window.location.hash = parcelHref(trackingNumber);
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

export function useHash(): string {
  return useSyncExternalStore(subscribe, () => window.location.hash);
}
