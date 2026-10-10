import { render } from "@testing-library/react";
import { vi } from "vitest";
import {
  FixtureCarrierClient,
  createParcelService,
  type ParcelService,
} from "@parcel/core";
import { App } from "../src/App";

/** The real parcel service over the sample shipments, with spies and per-test overrides. */
export function fakeService(overrides: Partial<ParcelService> = {}): ParcelService {
  const real = createParcelService(new FixtureCarrierClient());
  return {
    getParcel: vi.fn(real.getParcel),
    listParcels: vi.fn(real.listParcels),
    ...overrides,
  };
}

export function renderApp(service: ParcelService, hash = "#/") {
  window.location.hash = hash;
  return render(<App service={service} />);
}

export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}
