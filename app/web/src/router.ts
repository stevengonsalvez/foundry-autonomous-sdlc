import { useSyncExternalStore } from "react";

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
  const path = hash.replace(/^#/, "");
  if (path === "" || path === "/") return { name: "home" };
  const match = /^\/parcel\/([^/]+)$/.exec(path);
  return match ? { name: "parcel", trackingNumber: decode(match[1] ?? "") } : { name: "unknown" };
}

export const HOME_HREF = "#/";

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
