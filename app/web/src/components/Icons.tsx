import type { ReactNode } from "react";
import type { ParcelStatus } from "@parcel/core";

function Svg({ children, size = 16 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

const STATUS_ICONS: Record<ParcelStatus, ReactNode> = {
  label_created: (
    <>
      <path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8Z" />
      <circle cx="7.5" cy="7.5" r="1.2" />
    </>
  ),
  in_transit: (
    <>
      <path d="M2 6h12v10H2zM14 9h4l4 4v3h-8z" />
      <circle cx="7" cy="18" r="2" />
      <circle cx="18" cy="18" r="2" />
    </>
  ),
  out_for_delivery: (
    <>
      <path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11Z" />
      <circle cx="12" cy="10" r="2.5" />
    </>
  ),
  delivered: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m8 12.5 2.8 2.8L16 9.5" />
    </>
  ),
  exception: (
    <>
      <path d="M12 3 2 20h20L12 3Z" />
      <path d="M12 10v4M12 17.2v.1" />
    </>
  ),
};

export function StatusIcon({ status }: { status: ParcelStatus }) {
  return <Svg>{STATUS_ICONS[status]}</Svg>;
}

export function ArrowLeftIcon() {
  return (
    <Svg>
      <path d="M19 12H5M11 6l-6 6 6 6" />
    </Svg>
  );
}

export function ArrowRightIcon() {
  return (
    <Svg>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </Svg>
  );
}

export function BoxIcon() {
  return (
    <Svg size={22}>
      <path d="M21 8 12 3 3 8v8l9 5 9-5V8Z" />
      <path d="m3 8 9 5 9-5M12 13v8" />
    </Svg>
  );
}

export function LocationPinIcon({ size = 14 }: { size?: number } = {}) {
  return (
    <Svg size={size}>
      <path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11Z" />
      <circle cx="12" cy="10" r="2.5" />
    </Svg>
  );
}

export const PinIcon = LocationPinIcon;

export function CopyIcon({ size = 14 }: { size?: number } = {}) {
  return (
    <Svg size={size}>
      <rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
      <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
    </Svg>
  );
}

export function CheckIcon({ size = 14 }: { size?: number } = {}) {
  return (
    <Svg size={size}>
      <path d="M20 6 9 17l-5-5" />
    </Svg>
  );
}
