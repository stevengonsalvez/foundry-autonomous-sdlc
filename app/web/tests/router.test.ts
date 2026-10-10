import { describe, expect, it } from "vitest";
import { parcelHref, parseRoute } from "../src/router";

describe("parseRoute", () => {
  it.each(["", "#", "#/", "/"])("treats %j as the home page", (hash) => {
    expect(parseRoute(hash)).toEqual({ name: "home" });
  });

  it("reads the tracking number from a parcel route", () => {
    expect(parseRoute("#/parcel/PK1000000001")).toEqual({ name: "parcel", trackingNumber: "PK1000000001" });
  });

  it("decodes the tracking number", () => {
    expect(parseRoute("#/parcel/PK%201%2F2")).toEqual({ name: "parcel", trackingNumber: "PK 1/2" });
  });

  it("keeps undecodable text as typed", () => {
    expect(parseRoute("#/parcel/%E0%A4%A")).toEqual({ name: "parcel", trackingNumber: "%E0%A4%A" });
  });

  it.each(["#/parcel", "#/parcel/", "#/parcel/a/b", "#/elsewhere"])("does not know %j", (hash) => {
    expect(parseRoute(hash)).toEqual({ name: "unknown" });
  });
});

describe("parcelHref", () => {
  it("builds a hash link that round-trips through parseRoute", () => {
    const href = parcelHref("PK 1/2");
    expect(href).toBe("#/parcel/PK%201%2F2");
    expect(parseRoute(href)).toEqual({ name: "parcel", trackingNumber: "PK 1/2" });
  });
});
