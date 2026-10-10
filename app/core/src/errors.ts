export class InvalidTrackingNumberError extends Error {
  constructor(readonly input: string) {
    super(`Invalid tracking number: ${JSON.stringify(input)}`);
    this.name = "InvalidTrackingNumberError";
  }
}

export class ParcelNotFoundError extends Error {
  constructor(readonly trackingNumber: string) {
    super(`No parcel with tracking number ${trackingNumber}`);
    this.name = "ParcelNotFoundError";
  }
}

export class CarrierUnavailableError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "CarrierUnavailableError";
  }
}
