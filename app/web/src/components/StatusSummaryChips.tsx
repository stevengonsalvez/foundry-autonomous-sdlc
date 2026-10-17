import type React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ParcelStatus, ParcelSummary } from "@parcel/core";
import { PARCEL_STATUSES } from "@parcel/core";
import { STATUS_LABELS } from "./StatusBadge";

export interface StatusSummaryChipsProps {
  parcels: ParcelSummary[];
  selectedStatus: ParcelStatus | "all";
  onSelect: (status: ParcelStatus | "all") => void;
}

interface ChipItem {
  value: ParcelStatus | "all";
  label: string;
  count: number;
}

export function StatusSummaryChips({ parcels, selectedStatus, onSelect }: StatusSummaryChipsProps) {
  const counts = useMemo(() => {
    const map: Record<ParcelStatus, number> = {
      label_created: 0,
      in_transit: 0,
      out_for_delivery: 0,
      delivered: 0,
      exception: 0,
    };
    for (const parcel of parcels) {
      if (parcel.status in map) {
        map[parcel.status] = (map[parcel.status] ?? 0) + 1;
      }
    }
    return map;
  }, [parcels]);

  const chips: ChipItem[] = useMemo(
    () => [
      { value: "all", label: "All", count: parcels.length },
      ...PARCEL_STATUSES.map((status) => ({
        value: status,
        label: STATUS_LABELS[status],
        count: counts[status] ?? 0,
      })),
    ],
    [parcels.length, counts],
  );

  const activeIndex = useMemo(() => {
    const idx = chips.findIndex((c) => c.value === selectedStatus);
    return idx >= 0 ? idx : 0;
  }, [chips, selectedStatus]);

  const [focusedIndex, setFocusedIndex] = useState(activeIndex);
  const buttonRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    setFocusedIndex(activeIndex);
  }, [activeIndex]);

  const handleKeyDown = (index: number, e: React.KeyboardEvent<HTMLButtonElement>) => {
    let nextIndex: number | null = null;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      nextIndex = (index + 1) % chips.length;
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      nextIndex = (index - 1 + chips.length) % chips.length;
    } else if (e.key === "Home") {
      e.preventDefault();
      nextIndex = 0;
    } else if (e.key === "End") {
      e.preventDefault();
      nextIndex = chips.length - 1;
    }

    if (nextIndex !== null) {
      setFocusedIndex(nextIndex);
      buttonRefs.current[nextIndex]?.focus();
    }
  };

  return (
    <div
      className="status-summary-chips"
      data-testid="status-summary-chips"
      role="group"
      aria-label="Filter parcels by status"
    >
      {chips.map((chip, index) => {
        const isSelected = selectedStatus === chip.value;
        return (
          <button
            key={chip.value}
            ref={(el) => {
              buttonRefs.current[index] = el;
            }}
            type="button"
            className="status-summary-chip"
            aria-pressed={isSelected}
            tabIndex={focusedIndex === index ? 0 : -1}
            onClick={() => onSelect(chip.value)}
            onFocus={() => setFocusedIndex(index)}
            onKeyDown={(e) => handleKeyDown(index, e)}
          >
            <span className="status-summary-chip__label">{chip.label}</span>{" "}
            <span className="status-summary-chip__count">({chip.count})</span>
          </button>
        );
      })}
    </div>
  );
}
